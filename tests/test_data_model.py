"""P4 数据模型升级单测：settings 单行表、sessions.is_seed、status 枚举迁移。"""

import sqlite3

import pytest

from app import crud, db
from app.config import settings


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    db.init_db()
    yield


# —— settings 单行表 —— #


def test_target_band_roundtrip(tmp_db):
    assert crud.get_target_band() is None          # schema 种子行，初始未设置
    crud.set_target_band(6.5)
    assert crud.get_target_band() == 6.5
    crud.set_target_band(7.0)                      # UPSERT 覆盖，不增行
    assert crud.get_target_band() == 7.0
    crud.set_target_band(None)                     # 清除
    assert crud.get_target_band() is None


def test_settings_single_row_enforced(tmp_db):
    with db.get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM settings").fetchone()["n"]
        assert n == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO settings (id, target_band) VALUES (2, 5.0)")


# —— sessions.is_seed —— #


def test_is_seed_default_false(tmp_db):
    crud.create_session(
        session_id="s1", mode="ielts", sub_mode="exam", scenario_case=None,
        audio_path=None, duration_s=None, status="live",
    )
    assert crud.get_session("s1")["is_seed"] == 0


def test_is_seed_true_persists(tmp_db):
    crud.create_session(
        session_id="s2", mode="scenario", sub_mode=None, scenario_case="ordering",
        audio_path=None, duration_s=10.0, status="completed", is_seed=True,
    )
    assert crud.get_session("s2")["is_seed"] == 1


# —— 旧库迁移（init_db 幂等拉齐目标态）—— #


def test_init_db_migrates_legacy_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "legacy.db"))
    # 手造升级前的 sessions 表：无 is_seed 列、status 还是旧枚举
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, mode TEXT NOT NULL, "
        "sub_mode TEXT, scenario_case TEXT, started_at TEXT, duration_s REAL, "
        "audio_path TEXT, status TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sessions (id, mode, status) VALUES "
        "('old-done','ielts','done'), ('old-rec','ielts','recording'), "
        "('old-up','ielts','uploaded')"
    )
    conn.commit()
    conn.close()

    db.init_db()

    with db.get_connection() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(sessions)")}
        assert "is_seed" in cols                                   # 幂等补列
        rows = {
            r["id"]: r for r in c.execute("SELECT id, status, is_seed FROM sessions")
        }
        assert rows["old-done"]["status"] == "completed"           # done → completed
        assert rows["old-rec"]["status"] == "live"                 # recording → live
        assert rows["old-up"]["status"] == "uploaded"              # 过渡态保留（P4c 移除）
        assert rows["old-done"]["is_seed"] == 0                    # 旧行补默认值
        # settings 表 + 种子行也一并就位
        n = c.execute("SELECT COUNT(*) AS n FROM settings").fetchone()["n"]
        assert n == 1

    db.init_db()                                                   # 再跑一遍仍幂等
    with db.get_connection() as c:
        assert (
            c.execute("SELECT status FROM sessions WHERE id='old-done'").fetchone()["status"]
            == "completed"
        )


def test_migration_does_not_touch_new_recording_rows(tmp_db):
    # review C1/W4 防御：迁移已按 user_version 门控跑过后，方式 B（P4c）产生的
    # recording 活跃行在任意次重启 init_db 后必须原样保留，绝不被误迁成 live
    crud.create_session(
        session_id="b1", mode="ielts", sub_mode="module_p2", scenario_case=None,
        audio_path=None, duration_s=None, status="recording",
    )
    db.init_db()                                                   # 模拟重启
    assert crud.get_session("b1")["status"] == "recording"