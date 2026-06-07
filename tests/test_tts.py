"""题库 TTS 预生成单测：朗读文本组装 / WAV 封装 / 增量与失败降级（合成被 mock）。"""

import wave

import pytest

import app.tts as tts_module
from app.tts import compose_tts_text, generate_all, write_wav


def test_compose_plain_question_reads_text_as_is():
    q = {"id": "p1-01", "text": "Where is your hometown?"}
    assert compose_tts_text(q) == "Where is your hometown?"


def test_compose_cue_card_reads_topic_only():
    # 对齐拍板 D4（2026-06-07）：bullets 不口播——卡上展示即可，与 live 考官同规
    q = {
        "id": "p2-01",
        "text": "Describe a skill you would like to learn.",
        "bullets": ["what the skill is", "why you want to learn it",
                    "how you would learn it", "and explain how it would help you"],
    }
    out = compose_tts_text(q)
    assert out == "Describe a skill you would like to learn."
    assert "You should say" not in out and "bullet" not in out.lower()


def test_write_wav_format(tmp_path):
    path = tmp_path / "x.wav"
    write_wav(path, b"\x00\x01" * 2400)
    with wave.open(str(path), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
        assert w.getnframes() == 2400


def test_generate_all_incremental_and_failure_degrade(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_module, "TTS_DIR", tmp_path)
    monkeypatch.setattr(tts_module, "TTS_THROTTLE_S", 0)   # mock 测试不真睡节流
    calls = []

    def fake_synthesize(text):
        calls.append(text)
        if len(calls) == 2:
            raise RuntimeError("上游抖动")   # 单题失败不拖死全程
        return b"\x00\x00" * 240

    monkeypatch.setattr(tts_module, "synthesize", fake_synthesize)
    stats = generate_all()
    total = stats["generated"] + stats["failed"]
    assert stats["failed"] == 1
    assert stats["generated"] == total - 1 and total >= 20   # 全题库扫过

    # 再跑：已生成的跳过，只补失败那题
    calls.clear()
    stats2 = generate_all()
    assert stats2["skipped"] == stats["generated"]
    assert stats2["generated"] == 1 and len(calls) == 1


def test_compose_ignores_bullets_shape_variants():
    # D4 后 bullets 任何形态（缺失/单条/多条）都不影响朗读文本
    assert compose_tts_text({"id": "x", "text": "T."}) == "T."
    assert compose_tts_text({"id": "x", "text": "T.", "bullets": ["only item"]}) == "T."


def test_429_retry_then_success(monkeypatch):
    from google.genai import errors
    import app.tts as t

    monkeypatch.setattr(t, "TTS_429_RETRY_S", 0)
    attempts = []

    def flaky(text):
        attempts.append(1)
        if len(attempts) <= 2:
            raise errors.ClientError(429, {"error": {"code": 429, "message": "quota"}})
        return b"\x00\x00" * 10

    monkeypatch.setattr(t, "synthesize", flaky)
    assert t._synthesize_with_quota_retry("hi") == b"\x00\x00" * 10
    assert len(attempts) == 3
