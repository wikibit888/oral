"""音频文件落盘与契约校验：录音上传与回合切片共用。"""

import io
import wave
from pathlib import Path

from app.config import settings

# 固定音频契约（CLAUDE.md：mic in 16kHz / 16-bit / 单声道 PCM，无转码）
EXPECTED_SAMPLE_RATE = 16000
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2  # 字节，= 16-bit


def _audio_dir() -> Path:
    d = Path(settings.audio_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_wav(data: bytes) -> float:
    """解析 WAV 头、强制固定音频契约（16kHz / 单声道 / 16-bit / 非空），返回时长秒。

    违约抛 ValueError（中文文案，端点层转 422）。契约「固定、无转码」——不做隐式
    重采样，把不合规音频挡在流水线之外。非 PCM 压缩编码被 wave.open 当非法挡下。
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            channels = w.getnchannels()
            width = w.getsampwidth()
    except (wave.Error, EOFError):
        raise ValueError("audio 必须是合法的 WAV 文件")
    if rate != EXPECTED_SAMPLE_RATE:
        raise ValueError(f"采样率必须是 {EXPECTED_SAMPLE_RATE}Hz（收到 {rate}Hz）")
    if channels != EXPECTED_CHANNELS:
        raise ValueError(f"必须是单声道 mono（收到 {channels} 声道）")
    if width != EXPECTED_SAMPLE_WIDTH:
        raise ValueError(f"必须是 16-bit PCM（收到 {width * 8}-bit）")
    if frames == 0:
        raise ValueError("音频不能为空（0 帧）")
    return round(frames / rate, 3)


def save_recording(session_id: str, data: bytes) -> str:
    """把整段录音写为 {session_id}.wav，返回落盘路径。"""
    path = _audio_dir() / f"{session_id}.wav"
    path.write_bytes(data)
    return str(path)


def save_question_clip(session_id: str, question_id: str, data: bytes) -> str:
    """把方式 B 的单题录音（完整 WAV）写为 {session_id}_{question_id}.wav。

    question_id 由端点层白名单校验（防路径注入），本函数只管落盘。
    """
    path = _audio_dir() / f"{session_id}_{question_id}.wav"
    path.write_bytes(data)
    return str(path)


def delete_session_audio(session_id: str) -> int:
    """物理删除一个会话的全部音频文件（Give Up 不留痕），返回删除文件数。"""
    deleted = 0
    for p in _audio_dir().glob(f"{session_id}*.wav"):
        p.unlink(missing_ok=True)
        deleted += 1
    return deleted


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
