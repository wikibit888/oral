"""客观信号确定性单测。不依赖 faster-whisper，用合成词序列驱动。"""

from dataclasses import asdict

from app.models import Word
from app.signals import compute_signals

# 合成一段：含大小写/标点（测归一化）、相邻重复词、填充词、
# 0.3s 静默与 1.0s 犹豫、一个低频词（serendipity）。
WORDS = [
    Word(" I", 0.0, 0.2, 0.9),
    Word(" I", 0.2, 0.4, 0.9),          # 相邻重复 -> self-correction
    Word(" think", 0.4, 0.7, 0.9),
    Word(" um,", 0.7, 0.9, 0.9),        # 填充词
    Word(" science", 1.9, 2.4, 0.9),    # 与上一词 gap=1.0 -> 犹豫(也是静默)
    Word(" is", 2.4, 2.6, 0.9),
    Word(" is", 2.6, 2.8, 0.9),         # 相邻重复 -> self-correction
    Word(" serendipity.", 3.1, 3.4, 0.9),  # gap=0.3 -> 静默；低频词
]
DURATION = 3.5


def test_signals_values():
    s = compute_signals(WORDS, DURATION)

    assert s.word_count == 8
    assert s.duration_s == 3.5

    # 停顿
    assert s.pauses.silence_count == 2
    assert s.pauses.silence_total_s == 1.3
    assert s.pauses.hesitation_count == 1
    assert s.pauses.hesitation_total_s == 1.0
    assert s.pauses.silence_ratio == 0.3714

    # 语速
    assert s.speaking_time_s == 2.2
    assert s.gross_wpm == 137.1
    assert s.articulation_rate_wpm == 218.2

    # 填充词
    assert s.filler_count == 1
    assert s.filler_breakdown == {"um": 1}
    assert s.filler_per_min == 17.14

    # 自我更正（启发式）
    assert s.self_corrections_heuristic is True
    assert [(c.kind, c.text) for c in s.self_corrections] == [
        ("repeat_word", "i"),
        ("repeat_word", "is"),
    ]

    # 词汇
    assert s.distinct_word_count == 5
    assert s.type_token_ratio == 0.7143
    assert s.vocabulary_diversity_pct == 71.4
    assert s.repeated_words == {"i": 2, "is": 2}
    assert s.low_frequency_word_count == 1   # serendipity


def test_deterministic():
    """同一输入两次评分必须逐字段一致（零漂移）。"""
    assert asdict(compute_signals(WORDS, DURATION)) == asdict(
        compute_signals(WORDS, DURATION)
    )


def test_empty_input():
    s = compute_signals([], 0.0)
    assert s.word_count == 0
    assert s.gross_wpm == 0.0
    assert s.articulation_rate_wpm == 0.0
    assert s.type_token_ratio == 0.0
    assert s.pauses.silence_count == 0
    assert s.self_corrections == []
