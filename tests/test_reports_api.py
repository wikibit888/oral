"""HTTP 层单测：GET /reports/{id} 轮询契约 + POST /recordings 触发后台流水线。

DB 用临时文件；流水线被 mock，不跑真 whisper/Gemini。
"""

import io
import wave

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


def _wav_bytes(seconds=1.0, rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


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


def test_get_report_done_returns_full_report(client):
    crud.create_session(
        session_id="d1", mode="scenario", sub_mode=None, scenario_case="ordering",
        audio_path="/x.wav", duration_s=3.0, status="done",
    )
    crud.create_report(
        session_id="d1", mode="scenario", overall_band=None,
        fc_band=None, lr_band=None, gra_band=None, pron_band=None,
        wpm=120.0, silence_ratio=0.1, filler_pm=2.0, ttr=0.8, error_rate=None,
        report_json=_report_json(),
    )
    body = client.get("/reports/d1").json()
    assert body["status"] == "done"
    assert body["mode"] == "scenario"
    assert body["report"]["diagnostics"]["vocabulary_diversity_pct"] == 75.0
    assert body["report"]["overall_band"] is None


def test_get_report_done_but_no_report_row(client):
    # 边界：状态已 done 但 reports 行缺失（如置 done 后报告被清）——接口不崩，report 为 null
    crud.create_session(
        session_id="d2", mode="ielts", sub_mode="module_p2", scenario_case=None,
        audio_path="/x.wav", duration_s=3.0, status="done",
    )
    body = client.get("/reports/d2").json()
    assert body["status"] == "done"
    assert body["report"] is None


def test_post_recording_schedules_pipeline(client, monkeypatch):
    calls = []
    # 拦截后台流水线，避免跑真 whisper/Gemini，只验证被调度
    monkeypatch.setattr("app.api.recordings.process_session", lambda sid: calls.append(sid))

    r = client.post(
        "/recordings",
        files={"audio": ("a.wav", _wav_bytes(), "audio/wav")},
        data={"mode": "ielts", "sub_mode": "module_p2"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "uploaded"
    # 后台任务在响应后执行，TestClient 会等其跑完
    assert calls == [body["id"]]
