"""人机对话回看接口单测：GET /sessions/{id}/dialog + 逐轮音频取流。

DB 用临时文件；音频写真 WAV 到临时目录（端点不依赖 examiner 捕获，直接对已落盘切片服务）。
"""

import pytest
from fastapi.testclient import TestClient

from app import crud, storage
from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "audio_dir", str(tmp_path / "audio"))
    with TestClient(app) as c:
        yield c


def _mk_session(sid="s1", mode="scenario", scenario_case="ordering"):
    crud.create_session(
        session_id=sid, mode=mode, sub_mode=None, scenario_case=scenario_case,
        audio_path=None, duration_s=None, status="completed",
    )


def _silence(seconds=0.3) -> bytes:
    return b"\x00" * (32000 * int(seconds * 10) // 10)  # 16k×16bit×mono


def test_dialog_unknown_session_404(client):
    assert client.get("/sessions/nope/dialog").status_code == 404


def test_dialog_ordered_by_start_ts_with_roles_and_audio(client):
    _mk_session()
    # 故意乱序插入：start_ts 决定最终顺序（不是插入/ id 顺序）
    user_clip = storage.save_clip("s1", 0, _silence())
    crud.create_turn(session_id="s1", role="user", clip_path=user_clip, start_ts=2.0, text="thanks")
    ai_clip = storage.save_examiner_clip("s1", 0, _silence())
    crud.create_turn(session_id="s1", role="assistant", clip_path=ai_clip, start_ts=1.0, text="welcome")
    crud.create_turn(session_id="s1", role="user", clip_path=None, start_ts=0.0, text="hi")

    body = client.get("/sessions/s1/dialog").json()
    assert body["mode"] == "scenario"
    assert body["scenario_case"] == "ordering"
    rows = body["turns"]
    assert [r["role"] for r in rows] == ["user", "assistant", "user"]
    assert [r["start_ts"] for r in rows] == [0.0, 1.0, 2.0]
    assert [r["text"] for r in rows] == ["hi", "welcome", "thanks"]
    # 有切片才有 audio_url；无切片为 None
    assert rows[0]["audio_url"] is None
    assert rows[1]["audio_url"] == f"/sessions/s1/turns/{rows[1]['turn_id']}/audio"
    assert rows[2]["audio_url"] is not None


def test_dialog_null_start_ts_sorts_last(client):
    _mk_session()
    crud.create_turn(session_id="s1", role="assistant", clip_path=None, start_ts=5.0, text="late")
    crud.create_turn(session_id="s1", role="user", clip_path=None, start_ts=None, text="no-ts")
    rows = client.get("/sessions/s1/dialog").json()["turns"]
    # start_ts=None 排到最后（NULLS LAST），即便它先插入/可能 id 更小
    assert [r["text"] for r in rows] == ["late", "no-ts"]


def test_turn_audio_served(client):
    _mk_session()
    clip = storage.save_clip("s1", 0, _silence(0.5))
    tid = crud.create_turn(session_id="s1", role="user", clip_path=clip, start_ts=0.0, text="hi")
    r = client.get(f"/sessions/s1/turns/{tid}/audio")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"          # 真 WAV


def test_turn_audio_404_when_no_clip(client):
    _mk_session()
    tid = crud.create_turn(session_id="s1", role="user", clip_path=None, start_ts=0.0)
    assert client.get(f"/sessions/s1/turns/{tid}/audio").status_code == 404


def test_turn_audio_404_when_session_mismatch(client):
    _mk_session("s1")
    _mk_session("s2")
    clip = storage.save_clip("s1", 0, _silence())
    tid = crud.create_turn(session_id="s1", role="user", clip_path=clip, start_ts=0.0)
    # 用 s2 取 s1 的回合 → 越权拒绝
    assert client.get(f"/sessions/s2/turns/{tid}/audio").status_code == 404


def test_turn_audio_404_on_path_outside_audio_dir(client):
    _mk_session()
    tid = crud.create_turn(session_id="s1", role="user", clip_path="/etc/passwd", start_ts=0.0)
    assert client.get(f"/sessions/s1/turns/{tid}/audio").status_code == 404
