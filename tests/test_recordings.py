"""POST /recordings 上传校验单测，聚焦固定音频契约（16k/mono/16bit）的强制。

process_session 被 monkeypatch 成 no-op，合法上传不触发真 whisper/Gemini；DB/音频用临时路径。
"""

import io
import wave

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "audio_dir", str(tmp_path / "audio"))
    # 合法上传会在后台调度流水线——换成 no-op，避免跑真 whisper/Gemini
    monkeypatch.setattr("app.api.recordings.process_session", lambda sid: None)
    with TestClient(app) as c:
        yield c


def _wav_bytes(*, seconds=1.0, rate=16000, channels=1, width=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * (width * channels) * int(rate * seconds))
    return buf.getvalue()


def _post(client, data: bytes, *, mode="ielts", sub_mode="module_p2", scenario_case=None):
    form = {"mode": mode}
    if sub_mode is not None:
        form["sub_mode"] = sub_mode
    if scenario_case is not None:
        form["scenario_case"] = scenario_case
    return client.post(
        "/recordings",
        files={"audio": ("a.wav", data, "audio/wav")},
        data=form,
    )


# —— 合规音频：通过 —— #
def test_compliant_16k_mono_16bit_accepted(client):
    r = _post(client, _wav_bytes(seconds=2.5))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "uploaded"
    assert body["duration_s"] == 2.5


# —— 违约格式：一律 422 —— #
def test_wrong_sample_rate_rejected(client):
    r = _post(client, _wav_bytes(rate=44100))
    assert r.status_code == 422
    assert "采样率" in r.json()["detail"]


def test_stereo_rejected(client):
    r = _post(client, _wav_bytes(channels=2))
    assert r.status_code == 422
    assert "单声道" in r.json()["detail"]


def test_8bit_rejected(client):
    r = _post(client, _wav_bytes(width=1))
    assert r.status_code == 422
    assert "16-bit" in r.json()["detail"]


def test_combined_violation_rejected(client):
    # 48k/stereo/32bit：多项违约，按检查顺序命中第一项（采样率）即 422，其余违约为潜在
    r = _post(client, _wav_bytes(rate=48000, channels=2, width=4))
    assert r.status_code == 422


def test_empty_audio_rejected(client):
    # 格式合规但 0 帧（空音频）→ 422，避免流水线跑全零信号
    r = _post(client, _wav_bytes(seconds=0.0))
    assert r.status_code == 422
    assert "0 帧" in r.json()["detail"]


# —— 合法性校验仍保留 —— #
def test_non_wav_rejected(client):
    r = _post(client, b"this is definitely not a wav file")
    assert r.status_code == 422
    assert "合法的 WAV" in r.json()["detail"]
