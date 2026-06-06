"""转写数据结构。

单独成模块，让客观信号计算（signals）只依赖纯数据类、不依赖 faster-whisper，
便于确定性单测。
"""

import json
from dataclasses import asdict, dataclass


@dataclass
class Word:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class Transcript:
    text: str
    language: str
    duration: float
    words: list[Word]


@dataclass
class AudioClip:
    """judge 发音判定用的音频切片引用（P1 增量流水线）。

    file_uri 是 Files API 预上传结果；为 None 时 judge 回退 inline bytes。
    """

    path: str
    duration_s: float
    file_uri: str | None = None


def transcript_to_json(tr: Transcript) -> str:
    """Transcript → JSON 字符串（turns.transcript_json 落库用）。"""
    return json.dumps(asdict(tr), ensure_ascii=False)


def transcript_from_json(raw: str) -> Transcript:
    """turns.transcript_json → Transcript（finalize 时合并信号用）。"""
    d = json.loads(raw)
    return Transcript(
        text=d["text"],
        language=d["language"],
        duration=d["duration"],
        words=[Word(**w) for w in d["words"]],
    )
