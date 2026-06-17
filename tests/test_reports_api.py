"""HTTP 层单测：GET /reports/{id} 轮询契约。

DB 用临时文件；流水线被 mock，不跑真 whisper/Gemini。
"""

import pytest
from fastapi.testclient import TestClient

from app import crud, db
from app.config import settings
from app.main import app
from app.report import (
    Diagnostics,
    PracticeSummary,
    Report,
    SyntacticAnalysis,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """临时 DB + 临时音频目录 + TestClient（lifespan 会按临时路径建表）。"""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "audio_dir", str(tmp_path / "audio"))
    with TestClient(app) as c:
        yield c


def _report_json() -> str:
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=3.0, sessions=1, recordings=1),
        dimensions=None, overall_band=None,
        diagnostics=Diagnostics(
            common_patterns=[], syntactic_analysis=SyntacticAnalysis(observation="o", suggestion="s"),
            frequent_errors=[], fossilized_errors=[], self_corrections=[],
            vocabulary_diversity_pct=75.0, top_priorities=[], rewrites=[],
        ),
    ).model_dump_json()


def test_get_report_unknown_session_404(client):
    assert client.get("/reports/does-not-exist").status_code == 404


def test_get_report_while_processing_has_no_report(client):
    crud.create_session(
        session_id="p1", mode="ielts", sub_mode="module_p2", scenario_case=None,
        audio_path="/x.wav", duration_s=3.0, status="processing",
    )
    r = client.get("/reports/p1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "processing"
    assert body["report"] is None


def test_get_report_completed_returns_full_report(client):
    crud.create_session(
        session_id="d1", mode="scenario", sub_mode=None, scenario_case="ordering",
        audio_path="/x.wav", duration_s=3.0, status="completed",
    )
    crud.create_report(
        session_id="d1", mode="scenario", overall_band=None,
        fc_band=None, lr_band=None, gra_band=None, pron_band=None,
        wpm=120.0, silence_ratio=0.1, filler_pm=2.0, ttr=0.8, error_rate=None,
        report_json=_report_json(),
    )
    body = client.get("/reports/d1").json()
    assert body["status"] == "completed"
    assert body["mode"] == "scenario"
    assert body["report"]["diagnostics"]["vocabulary_diversity_pct"] == 75.0
    assert body["report"]["overall_band"] is None


def test_get_report_completed_but_no_report_row(client):
    # 边界：状态已 completed 但 reports 行缺失——接口不崩，report 为 null
    crud.create_session(
        session_id="d2", mode="ielts", sub_mode="module_p2", scenario_case=None,
        audio_path="/x.wav", duration_s=3.0, status="completed",
    )
    body = client.get("/reports/d2").json()
    assert body["status"] == "completed"
    assert body["report"] is None


def test_get_report_corrupt_json_degrades_not_500(client):
    # report_json 损坏 / schema 漂移：GET 不 500，降级 report=null（故障定位 #19）
    crud.create_session(
        session_id="d3", mode="ielts", sub_mode="exam", scenario_case=None,
        audio_path="/x.wav", duration_s=3.0, status="completed",
    )
    crud.create_report(
        session_id="d3", mode="ielts", overall_band=6.0,
        fc_band=6.0, lr_band=6.0, gra_band=6.0, pron_band=6.0,
        wpm=120.0, silence_ratio=0.1, filler_pm=2.0, ttr=0.8, error_rate=None,
        report_json='{"not":"a valid report"}',   # 缺 required 字段
    )
    r = client.get("/reports/d3")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["report"] is None


def _wait_for(predicate, timeout=2.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_retry_failed_session_flips_processing_and_runs_finalize(client, monkeypatch):
    # 失败会话可重跑恢复：POST /retry → processing + 后台 finalize 真被调用（故障定位 #18）
    import app.api.reports as reports_mod

    called = {}

    def fake_finalize(session_id):
        called["sid"] = session_id
        crud.update_session_status(session_id, "completed")

    monkeypatch.setattr(reports_mod, "finalize_session", fake_finalize)

    crud.create_session(
        session_id="r1", mode="ielts", sub_mode="exam", scenario_case=None,
        audio_path="/x.wav", duration_s=10.0, status="failed",
    )
    r = client.post("/reports/r1/retry")
    assert r.status_code == 200
    assert r.json()["status"] == "processing"
    # 后台线程跑 finalize（mock 即时置 completed）——轮询等它落地
    assert _wait_for(lambda: called.get("sid") == "r1")
    assert _wait_for(lambda: crud.get_session("r1")["status"] == "completed")


def test_retry_unknown_session_404(client):
    assert client.post("/reports/nope/retry").status_code == 404


def test_retry_inflight_dedup_skips_second_finalize(client, monkeypatch):
    # 在途去重（C1/W2 防 double-finalize）：同一 session 已有重跑在途时，再次 POST /retry
    # 直接返回 processing，不并发起第二个 finalize（前端 stalled 误判 / 连点都安全）。
    import app.api.reports as reports_mod

    called = []
    monkeypatch.setattr(reports_mod, "finalize_session", lambda sid: called.append(sid))
    crud.create_session(
        session_id="r6", mode="ielts", sub_mode="exam", scenario_case=None,
        audio_path="/x.wav", duration_s=10.0, status="failed",
    )
    reports_mod._retry_inflight.add("r6")          # 模拟已有在途重跑
    try:
        r = client.post("/reports/r6/retry")
        assert r.status_code == 200
        assert r.json()["status"] == "processing"
        assert called == []                        # 去重命中：未起第二个 finalize
    finally:
        reports_mod._retry_inflight.discard("r6")


def test_retry_rejects_in_progress_session(client):
    # live / recording 仍在进行中：不可重跑（409）
    crud.create_session(
        session_id="r2", mode="scenario", sub_mode=None, scenario_case="ordering",
        audio_path=None, duration_s=None, status="live",
    )
    assert client.post("/reports/r2/retry").status_code == 409


def test_retry_rejects_completed_with_valid_report(client):
    # completed 且报告体完好：绝不重跑（避免无谓 judge 调用 / 覆盖好报告）→ 409
    crud.create_session(
        session_id="r3", mode="scenario", sub_mode=None, scenario_case="ordering",
        audio_path="/x.wav", duration_s=3.0, status="completed",
    )
    crud.create_report(
        session_id="r3", mode="scenario", overall_band=None,
        fc_band=None, lr_band=None, gra_band=None, pron_band=None,
        wpm=120.0, silence_ratio=0.1, filler_pm=2.0, ttr=0.8, error_rate=None,
        report_json=_report_json(),
    )
    assert client.post("/reports/r3/retry").status_code == 409


def test_retry_allows_completed_with_broken_report(client, monkeypatch):
    # completed 但报告体损坏（GET 已降级 report=null）：这是死骨架的唯一出路——允许重跑（故障定位 #C2）
    import app.api.reports as reports_mod

    monkeypatch.setattr(
        reports_mod, "finalize_session", lambda sid: crud.update_session_status(sid, "completed")
    )
    crud.create_session(
        session_id="r4", mode="ielts", sub_mode="exam", scenario_case=None,
        audio_path="/x.wav", duration_s=3.0, status="completed",
    )
    crud.create_report(
        session_id="r4", mode="ielts", overall_band=6.0,
        fc_band=6.0, lr_band=6.0, gra_band=6.0, pron_band=6.0,
        wpm=120.0, silence_ratio=0.1, filler_pm=2.0, ttr=0.8, error_rate=None,
        report_json='{"broken":"schema"}',   # 损坏：缺 required 字段
    )
    r = client.post("/reports/r4/retry")
    assert r.status_code == 200
    assert r.json()["status"] == "processing"


def test_retry_completed_no_report_row_recoverable(client, monkeypatch):
    # completed 但 reports 行整个缺失：同属"无可渲染报告"，允许重跑
    import app.api.reports as reports_mod

    monkeypatch.setattr(
        reports_mod, "finalize_session", lambda sid: crud.update_session_status(sid, "completed")
    )
    crud.create_session(
        session_id="r5", mode="ielts", sub_mode="exam", scenario_case=None,
        audio_path="/x.wav", duration_s=3.0, status="completed",
    )
    assert client.post("/reports/r5/retry").status_code == 200
