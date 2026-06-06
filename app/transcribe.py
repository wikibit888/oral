"""faster-whisper 转写：对录音 / 切片跑词级时间戳，作为客观信号的输入。

要点：
- VAD 关闭——停顿 / 静默本身是评测信号（PRD §6.1），不能被 VAD 抹掉。
- word_timestamps=True——客观信号（语速 / 停顿 / 填充词）全建立在词级时间戳上。
- 模型懒加载 + 进程内单例，首次调用自动下载权重（默认 small，见 config）。
"""

from functools import lru_cache

from faster_whisper import WhisperModel

from app.config import settings
from app.models import Transcript, Word


@lru_cache(maxsize=1)
def _get_model() -> WhisperModel:
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def transcribe(audio_path: str) -> Transcript:
    """转写一个音频文件，返回带词级时间戳的结构化结果。"""
    model = _get_model()
    segments, info = model.transcribe(
        audio_path,
        language=settings.whisper_language or None,
        word_timestamps=True,
        vad_filter=False,
    )

    words: list[Word] = []
    text_parts: list[str] = []
    for seg in segments:
        text_parts.append(seg.text)
        for w in seg.words or []:
            words.append(
                Word(
                    word=w.word,
                    start=round(w.start, 3),
                    end=round(w.end, 3),
                    probability=round(w.probability, 4),
                )
            )

    return Transcript(
        text="".join(text_parts).strip(),
        language=info.language,
        duration=round(info.duration, 3),
        words=words,
    )
