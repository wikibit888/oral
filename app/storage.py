"""音频文件落盘：录音上传与课后切片共用。"""

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
