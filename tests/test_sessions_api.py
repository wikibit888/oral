"""方式 B 会话化接口单测（SCHEMA §6.2）：建会话 / 逐题上传 / Get Review / Give Up。

ingest / finalize 被 mock（真实现要跑 whisper/judge）；DB / 音频用临时路径。
音频契约校验（16k/mono/16bit/非空）覆盖自旧 POST /recordings 测试迁移。
"""

import io
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import crud
from app.api import sessions as sessions_module
from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "audio_dir", str(tmp_path / "audio"))
    with TestClient(app) as c:
        yield c
    sessions_module._ingest_tasks.clear()
    sessions_module._finalize_tasks.clear()


@pytest.fixture
def calls(monkeypatch):
    """掐掉真 ingest / finalize，记录调用（线程里跑，记录即返回）。"""
    record = {"ingest": [], "finalize": []}
    monkeypatch.setattr(
        "app.api.sessions.ingest_clip",
        lambda sid, clip: record["ingest"].append((sid, clip)),
    )
    monkeypatch.setattr(
        "app.api.sessions.finalize_session",
        lambda sid: record["finalize"].append(sid),
    )
    return record


def _wav_bytes(*, seconds=1.0, rate=16000, channels=1, width=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * (width * channels) * int(rate * seconds))
    return buf.getvalue()


def _create(client, sub_mode="module_p2") -> str:
    r = client.post("/sessions", json={"mode": "ielts", "sub_mode": sub_mode})
    assert r.status_code == 201
    return r.json()["session_id"]


def _upload(client, sid, data=None, question_id="p2-01"):
    return client.post(
        f"/sessions/{sid}/recordings",
        files={"audio": ("q.wav", data or _wav_bytes(), "audio/wav")},
        data={"question_id": question_id},
    )


def _wait_for(predicate, timeout=2.0, what="后台任务"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    pytest.fail(f"等待超时（{timeout}s）：{what} 未达成")


# ---------- POST /sessions ----------


def test_create_session_b_mode(client):
    sid = _create(client, "module_p1")
    row = crud.get_session(sid)
    assert row["mode"] == "ielts"
    assert row["sub_mode"] == "module_p1"
    assert row["status"] == "recording"
    assert row["scenario_case"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "scenario", "sub_mode": "module_p1"},   # 情景走 /ws/live
        {"mode": "ielts", "sub_mode": "exam"},           # 方式 A 走 /ws/live
        {"mode": "ielts", "sub_mode": "bogus"},
    ],
)
def test_create_session_rejects_non_b_modes(client, body):
    assert client.post("/sessions", json=body).status_code == 422


# ---------- POST /sessions/{id}/recordings ----------


def test_upload_accepts_and_schedules_ingest(client, calls):
    sid = _create(client)
    r = _upload(client, sid, question_id="p2-03")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "accepted"
    assert body["duration_s"] == 1.0

    # 切片落盘 + 时长同步累加 + ingest 后台调度
    clip = Path(settings.audio_dir) / f"{sid}_p2-03.wav"
    assert clip.exists()
    assert crud.get_session(sid)["duration_s"] == 1.0
    assert _wait_for(lambda: calls["ingest"] == [(sid, str(clip))])


def test_upload_accumulates_duration_across_questions(client, calls):
    sid = _create(client, "module_p1")
    _upload(client, sid, question_id="p1-01")
    _upload(client, sid, _wav_bytes(seconds=2.0), question_id="p1-02")
    assert crud.get_session(sid)["duration_s"] == 3.0


def test_upload_unknown_session_404(client, calls):
    assert _upload(client, "nope").status_code == 404


def test_upload_after_review_409(client, calls):
    sid = _create(client)
    _upload(client, sid)
    client.post(f"/sessions/{sid}/review")
    assert _upload(client, sid).status_code == 409   # 已进 processing


def test_upload_bad_question_id_422(client, calls):
    sid = _create(client)
    r = _upload(client, sid, question_id="../evil")
    assert r.status_code == 422
    assert "question_id" in r.json()["detail"]


@pytest.mark.parametrize(
    "data,fragment",
    [
        (b"not a wav at all", "合法的 WAV"),
        (None, "采样率"),          # 44.1k 在下方特判生成
        ("stereo", "单声道"),
        ("8bit", "16-bit"),
        ("empty", "0 帧"),
    ],
)
def test_upload_enforces_audio_contract(client, calls, data, fragment):
    # 覆盖自旧 POST /recordings 的格式契约测试（校验逻辑已迁 storage.validate_wav）
    sid = _create(client)
    if data is None:
        data = _wav_bytes(rate=44100)
    elif data == "stereo":
        data = _wav_bytes(channels=2)
    elif data == "8bit":
        data = _wav_bytes(width=1)
    elif data == "empty":
        data = _wav_bytes(seconds=0.0)
    r = _upload(client, sid, data)
    assert r.status_code == 422
    assert fragment in r.json()["detail"]


# ---------- POST /sessions/{id}/review ----------


def test_review_without_recording_422(client, calls):
    sid = _create(client)
    r = client.post(f"/sessions/{sid}/review")
    assert r.status_code == 422
    assert "尚无录音" in r.json()["detail"]


def test_review_flips_processing_and_finalizes_after_drain(client, calls):
    sid = _create(client)
    _upload(client, sid)
    r = client.post(f"/sessions/{sid}/review")
    assert r.status_code == 200
    assert r.json() == {"status": "processing"}
    assert crud.get_session(sid)["status"] == "processing"   # 立即翻转，无契约外状态
    assert _wait_for(lambda: calls["finalize"] == [sid])     # 排干在途 ingest 后触发


def test_review_twice_409(client, calls):
    sid = _create(client)
    _upload(client, sid)
    client.post(f"/sessions/{sid}/review")
    assert client.post(f"/sessions/{sid}/review").status_code == 409


def test_review_unknown_session_404(client, calls):
    assert client.post("/sessions/nope/review").status_code == 404


# ---------- DELETE /sessions/{id}（Give Up）----------


def test_give_up_deletes_row_and_audio(client, calls):
    sid = _create(client)
    _upload(client, sid, question_id="p2-01")
    _upload(client, sid, question_id="p2-02")
    clips = list(Path(settings.audio_dir).glob(f"{sid}*.wav"))
    assert len(clips) == 2

    r = client.delete(f"/sessions/{sid}")
    assert r.status_code == 204
    assert crud.get_session(sid) is None
    assert list(Path(settings.audio_dir).glob(f"{sid}*.wav")) == []


def test_give_up_unknown_session_404(client, calls):
    assert client.delete("/sessions/nope").status_code == 404


# ---------- 旧端点已移除 ----------


def test_old_recordings_endpoint_gone(client):
    r = client.post("/recordings")
    assert r.status_code in (404, 405)