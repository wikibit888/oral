"""Review 面板与设置接口单测（SCHEMA §6.4）：GET /progress + GET/PUT /settings。

数据经 crud 直插临时库（不跑真流水线）；started_at 显式回填控制时间序。
"""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import crud
from app.config import settings
from app.db import get_connection
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def _seed_session(
    *,
    mode="ielts",
    sub_mode="exam",
    scenario_case=None,
    status="completed",
    started_at=None,
    report=None,
) -> str:
    """插一条会话（可带报告行），回填 started_at 控制时间序。"""
    session_id = crud.create_session(
        session_id=uuid4().hex,
        mode=mode,
        sub_mode=sub_mode,
        scenario_case=scenario_case,
        audio_path=None,
        duration_s=60.0,
        status=status,
    )
    if started_at is not None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET started_at = ? WHERE id = ?",
                (started_at, session_id),
            )
    if report is not None:
        crud.create_report(
            session_id=session_id,
            mode=mode,
            overall_band=report.get("overall_band"),
            fc_band=report.get("fc_band"),
            lr_band=report.get("lr_band"),
            gra_band=report.get("gra_band"),
            pron_band=report.get("pron_band"),
            wpm=report.get("wpm"),
            silence_ratio=report.get("silence_ratio"),
            filler_pm=report.get("filler_pm"),
            ttr=report.get("ttr"),
            error_rate=report.get("error_rate"),
            report_json=json.dumps({}),
        )
    return session_id


# —— GET /settings / PUT /settings —— #


def test_settings_default_null(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert r.json() == {"target_band": None}


def test_settings_put_then_get_roundtrip(client):
    r = client.put("/settings", json={"target_band": 6.5})
    assert r.status_code == 200
    assert r.json() == {"target_band": 6.5}
    assert client.get("/settings").json() == {"target_band": 6.5}


def test_settings_put_null_clears(client):
    client.put("/settings", json={"target_band": 7.0})
    r = client.put("/settings", json={"target_band": None})
    assert r.status_code == 200
    assert client.get("/settings").json() == {"target_band": None}


@pytest.mark.parametrize("bad", [6.3, 9.5, -0.5, 100])
def test_settings_put_rejects_invalid_band(client, bad):
    assert client.put("/settings", json={"target_band": 6.0}).status_code == 200
    r = client.put("/settings", json={"target_band": bad})
    assert r.status_code == 422
    # 非法值不落库
    assert client.get("/settings").json() == {"target_band": 6.0}


def test_settings_put_accepts_half_steps(client):
    for band in (0, 4.5, 9):
        r = client.put("/settings", json={"target_band": band})
        assert r.status_code == 200, band


# —— GET /progress —— #


def test_progress_empty_db(client):
    r = client.get("/progress")
    assert r.status_code == 200
    assert r.json() == {
        "band_series": [],
        "fluency_series": [],
        "target_band": None,
        "latest_bands": None,
        "gap": None,
    }


def test_progress_series_filtering_and_order(client):
    # 方式 A 两条（乱序插入，靠 started_at 排序）
    _seed_session(
        started_at="2026-06-05T10:00:00.000Z",
        report={"overall_band": 6.0, "fc_band": 6.0, "lr_band": 6.0,
                "gra_band": 5.5, "pron_band": 6.5,
                "wpm": 100.0, "silence_ratio": 0.3, "filler_pm": 5.0,
                "error_rate": 2.0},
    )
    _seed_session(
        started_at="2026-06-03T10:00:00.000Z",
        report={"overall_band": 5.5, "fc_band": 5.5, "lr_band": 5.5,
                "gra_band": 5.0, "pron_band": 6.0,
                "wpm": 90.0, "silence_ratio": 0.4, "filler_pm": 7.0,
                "error_rate": 3.0},
    )
    # 方式 B：无 band，只进流利度
    _seed_session(
        sub_mode="module_p1",
        started_at="2026-06-04T10:00:00.000Z",
        report={"wpm": 95.0, "silence_ratio": 0.35, "filler_pm": 6.0},
    )
    # 情景：无 band，只进流利度
    _seed_session(
        mode="scenario", sub_mode=None, scenario_case="ordering",
        started_at="2026-06-06T10:00:00.000Z",
        report={"wpm": 110.0, "silence_ratio": 0.25, "filler_pm": 4.0},
    )
    # failed 会话：有报告行也不进任何曲线
    _seed_session(
        status="failed",
        started_at="2026-06-01T10:00:00.000Z",
        report={"overall_band": 9.0, "wpm": 999.0},
    )
    # completed 但 wpm 为 NULL（空转写降级）：不进流利度
    _seed_session(
        sub_mode="module_p2",
        started_at="2026-06-02T10:00:00.000Z",
        report={"wpm": None},
    )

    data = client.get("/progress").json()

    # band 轨迹：仅方式 A，时间升序
    assert [p["overall_band"] for p in data["band_series"]] == [5.5, 6.0]
    assert data["band_series"][0]["date"] == "2026-06-03T10:00:00.000Z"
    assert data["band_series"][1]["pron_band"] == 6.5

    # 流利度趋势：全模式（A×2 + B×1 + 情景×1），时间升序；failed / wpm NULL 不进
    assert [p["wpm"] for p in data["fluency_series"]] == [90.0, 95.0, 100.0, 110.0]
    assert data["fluency_series"][0]["error_rate"] == 3.0

    # 最新 band 点 = 升序末位
    assert data["latest_bands"]["overall_band"] == 6.0
    assert data["latest_bands"]["date"] == "2026-06-05T10:00:00.000Z"


def test_progress_gap_against_latest(client):
    _seed_session(
        started_at="2026-06-05T10:00:00.000Z",
        report={"overall_band": 6.0, "fc_band": 6.0, "lr_band": 6.5,
                "gra_band": 5.5, "pron_band": 6.0, "wpm": 100.0},
    )
    client.put("/settings", json={"target_band": 7.0})

    gap = client.get("/progress").json()["gap"]
    assert gap == {
        "overall_band": 1.0,
        "fc_band": 1.0,
        "lr_band": 0.5,      # 已接近目标
        "gra_band": 1.5,
        "pron_band": 1.0,
    }


def test_progress_gap_null_without_target_or_bands(client):
    # 无目标：有方式 A 报告也不出 gap
    _seed_session(report={"overall_band": 6.0, "wpm": 100.0})
    assert client.get("/progress").json()["gap"] is None

    # 有目标但无方式 A 报告：gap 仍 null（方式 B 不喂 band）
    client.put("/settings", json={"target_band": 7.0})
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
    _seed_session(sub_mode="module_p1", report={"wpm": 95.0})
    data = client.get("/progress").json()
    assert data["latest_bands"] is None
    assert data["gap"] is None
    assert data["target_band"] == 7.0


def test_progress_gap_negative_when_exceeding_target(client):
    # 已超出目标：gap 为负（契约「负 = 已超出」），不截断不取绝对值
    _seed_session(
        report={"overall_band": 8.0, "fc_band": 8.0, "lr_band": 7.5,
                "gra_band": 8.0, "pron_band": 8.5, "wpm": 130.0},
    )
    client.put("/settings", json={"target_band": 7.0})
    gap = client.get("/progress").json()["gap"]
    assert gap["overall_band"] == -1.0
    assert gap["lr_band"] == -0.5
    assert gap["pron_band"] == -1.5


def test_progress_gap_handles_missing_dimension(client):
    # judge 降级输出缺单维：该维 gap 为 null，整体不炸
    _seed_session(
        report={"overall_band": 6.0, "fc_band": 6.0, "lr_band": None,
                "gra_band": 5.5, "pron_band": 6.0, "wpm": 100.0},
    )
    client.put("/settings", json={"target_band": 7.0})
    gap = client.get("/progress").json()["gap"]
    assert gap["lr_band"] is None
    assert gap["fc_band"] == 1.0
