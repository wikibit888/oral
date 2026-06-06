"""转写数据结构。

单独成模块，让客观信号计算（signals）只依赖纯数据类、不依赖 faster-whisper，
便于确定性单测。
"""

from dataclasses import dataclass


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
