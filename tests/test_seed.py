"""demo seed 脚本单测（SCHEMA §5.3）：幂等性 / 爬升曲线 / 报告可渲染 / purge 边界。"""

import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import crud, seed as seed_module
from app.config import settings
from app.db import get_connection
from app.judge.aggregate import aggregate_overall_band
from app.main import app
from app.report import Report
from app.seed import SEED_SPECS, purge_seeds, seed

FIXED_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)

# SQLite 默认 started_at 格式：YYYY-MM-DDTHH:MM:SS.mmmZ
_STARTED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def _all_sessions():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()


def test_seed_inserts_specs_completed_and_marked(client):
    ids = seed(now=FIXED_NOW)
    assert ids == [s["id"] for s in SEED_SPECS]
    rows = _all_sessions()
    assert len(rows) == len(SEED_SPECS) == 7
    assert all(row["is_seed"] == 1 for row in rows)
    assert all(row["status"] == "completed" for row in rows)
    assert all(row["audio_path"] is None for row in rows)       # 无音频回放
    assert all(_STARTED_AT_RE.match(row["started_at"]) for row in rows)


def test_seed_idempotent_rerun(client):
    seed(now=FIXED_NOW)
    seed(now=FIXED_NOW)
    assert len(_all_sessions()) == 7
    with get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"]
    assert n == 7


def test_purge_only_removes_seed_rows(client):
    real = crud.create_session(
        session_id=uuid4().hex, mode="ielts", sub_mode="module_p1",
        scenario_case=None, audio_path=None, duration_s=60.0, status="recording",
    )
    seed(now=FIXED_NOW)
    assert purge_seeds() == 7
    rows = _all_sessions()
    assert [r["id"] for r in rows] == [real]                    # 真实行不受波及


def test_band_series_climbs_5_5_to_6_5(client):
    seed(now=FIXED_NOW)
    data = client.get("/progress").json()
    assert [p["overall_band"] for p in data["band_series"]] == [5.5, 6.0, 6.5]
    # overall 与四维真聚合一致（构造期已走 aggregate_overall_band，这里防数据漂移）
    for spec in SEED_SPECS:
        if spec["dims"] is not None:
            report = seed_module._build_report(spec)
            assert report.overall_band == aggregate_overall_band(spec["dims"])


def test_fluency_series_monotonic_improvement(client):
    seed(now=FIXED_NOW)
    series = client.get("/progress").json()["fluency_series"]
    assert len(series) == 7
    wpm = [p["wpm"] for p in series]
    silence = [p["silence_ratio"] for p in series]
    fillers = [p["filler_pm"] for p in series]
    errors = [p["error_rate"] for p in series]
    assert wpm == sorted(wpm) and len(set(wpm)) == 7            # 严格爬升
    assert silence == sorted(silence, reverse=True)             # 静默比下降
    assert fillers == sorted(fillers, reverse=True)             # 填充词下降
    assert errors == sorted(errors, reverse=True)               # 错误率下降
    # ttr 同步爬升（驱动各报告 vocabulary_diversity_pct，防调参时把曲线掰反）
    ttr = [s["ttr"] for s in SEED_SPECS]
    assert ttr == sorted(ttr) and len(set(ttr)) == 7


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_dimension_evidence_is_verbatim_english():
    """护城河铁律：evidence 只放考生原话逐字引用（英文/ASR 转写体），不放中文观察。"""
    for spec in SEED_SPECS:
        if spec["dims"] is None:
            continue
        dims = spec["dims"]
        for dim in (
            dims.fluency_coherence, dims.lexical_resource,
            dims.grammatical_range_accuracy, dims.pronunciation,
        ):
            assert dim.evidence, f"{spec['id']}: evidence 不得为空（引不出原话则不下判断）"
            for quote in dim.evidence:
                assert not _has_cjk(quote), f"{spec['id']}: evidence 混入中文: {quote!r}"


def test_scenario_seeds_summary_no_rewrites():
    """情景报告结构（用户决策 2026-06-07）：情景 seed 无改写示范、有中文末尾总结；
    雅思 seed 保留改写示范、不带 summary（schema 默认 None）。"""
    for spec in SEED_SPECS:
        diag = spec["diagnostics_judge"]
        if spec["mode"] == "scenario":
            assert diag["rewrites"] == [], f"{spec['id']}: 情景不出改写示范"
            assert diag["summary"] and _has_cjk(diag["summary"]), f"{spec['id']}: 情景总结缺失"
        else:
            assert diag["rewrites"], f"{spec['id']}: 雅思 seed 应保留改写示范"
            assert "summary" not in diag, f"{spec['id']}: summary 仅情景"


def test_seed_default_clock_path(client):
    # 不传 now 走 datetime.now(timezone.utc) 默认路径
    assert len(seed()) == 7
    assert len(_all_sessions()) == 7


def test_started_at_rejects_naive_datetime():
    with pytest.raises(ValueError):
        seed_module._started_at(datetime(2026, 6, 7, 12, 0, 0), 1)


def test_seed_reports_render_via_api(client):
    seed(now=FIXED_NOW)
    # 方式 A：有 band 四维 + overall
    a = client.get("/reports/seed-07").json()
    assert a["status"] == "completed"
    assert a["report"]["overall_band"] == 6.5
    assert a["report"]["dimensions"]["pronunciation"]["band"] == 7.0
    assert a["report"]["unscorable"] is False
    # 情景：无 band，诊断层完整；无改写示范、有末尾总结（用户决策 2026-06-07）
    s = client.get("/reports/seed-02").json()
    assert s["report"]["overall_band"] is None
    assert s["report"]["dimensions"] is None
    assert s["report"]["diagnostics"]["top_priorities"]
    assert s["report"]["diagnostics"]["rewrites"] == []
    assert s["report"]["diagnostics"]["summary"]
    # 方式 B：同样无 band
    b = client.get("/reports/seed-06").json()
    assert b["report"]["overall_band"] is None


def test_seed_report_json_passes_schema_and_backfill(client):
    seed(now=FIXED_NOW)
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM reports ORDER BY session_id").fetchall()
    for row in rows:
        report = Report.model_validate_json(row["report_json"])    # schema 必过
        assert report.diagnostics.vocabulary_diversity_pct == round(row["ttr"] * 100, 1)
        assert report.unscorable is False


def test_seed_rows_appear_in_library(client):
    seed(now=FIXED_NOW)
    rows = client.get("/sessions").json()
    assert len(rows) == 7
    assert all(r["is_seed"] is True for r in rows)
    # 倒序：最新（2 天前的方式 A 6.5）在最前
    assert rows[0]["id"] == "seed-07"
    assert rows[0]["overall_band"] == 6.5 and rows[0]["wpm"] == 118.0
    scenario = next(r for r in rows if r["scenario_case"] == "ordering")
    assert scenario["overall_band"] is None and scenario["wpm"] == 88.0
