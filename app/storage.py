"""音频文件落盘：录音上传与回合切片共用。"""

import wave
from pathlib import Path

from app.config import settings


def _audio_dir() -> Path:
    d = Path(settings.audio_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_recording(session_id: str, data: bytes) -> str:
    """把整段录音写为 {session_id}.wav，返回落盘路径。"""
    path = _audio_dir() / f"{session_id}.wav"
    path.write_bytes(data)
    return str(path)


def save_clip(session_id: str, seq: int, pcm: bytes) -> str:
    """把一个回合切片（16k/16-bit/mono 裸 PCM）封 WAV 头写盘，返回落盘路径。

    tee 出来的是裸 PCM 帧（契约固定格式，免转码），只需补 WAV 头给 whisper 读。
    序号三位零填充（假定单会话 ≤999 个切片，demo 量级远够）。
    """
    path = _audio_dir() / f"{session_id}_turn{seq:03d}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return str(path)
