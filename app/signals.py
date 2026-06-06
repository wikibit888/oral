"""客观信号计算（确定性、可单测）。

输入是词级时间戳序列；所有指标基于带时间戳的 token 算出，不调用 LLM、无随机——
同一输入恒得同一输出（PRD §6.1）。客观信号是 judge 的**输入**，不是最终成绩。
"""

import string
from dataclasses import dataclass

from wordfreq import zipf_frequency

from app.models import Word

# —— 阈值（命名常量，便于校准；改阈值不动逻辑）——
SILENCE_GAP_S = 0.3        # 相邻词间隔 ≥ 此值计静默
HESITATION_GAP_S = 1.0     # ≥ 此值计犹豫（长停顿），是静默的子集
FILLERS = frozenset({"um", "uh", "er", "erm", "hmm", "uhm", "mm"})
LOW_FREQ_ZIPF = 3.0        # zipf 介于 (0, 此值) 计低频（较高级）词；0 多为专有名词，不计


@dataclass
class PauseSignals:
    silence_count: int
    silence_total_s: float
    hesitation_count: int
    hesitation_total_s: float
    silence_ratio: float


@dataclass
class SelfCorrection:
    kind: str        # repeat_word | repeat_bigram
    text: str


@dataclass
class ObjectiveSignals:
    word_count: int
    duration_s: float
    speaking_time_s: float
    gross_wpm: float
    articulation_rate_wpm: float
    pauses: PauseSignals
    filler_count: int
    filler_per_min: float
    filler_breakdown: dict[str, int]
    self_corrections: list[SelfCorrection]
    self_corrections_heuristic: bool   # 启发式、有误差（PRD §6.1 明确标注）
    type_token_ratio: float
    vocabulary_diversity_pct: float
    distinct_word_count: int
    low_frequency_word_count: int
    repeated_words: dict[str, int]


def _normalize(raw: str) -> str:
    """去首尾空白与标点、转小写；内部撇号（如 i'm）保留。"""
    return raw.strip().lower().strip(string.punctuation + " ")


def compute_signals(words: list[Word], duration_s: float) -> ObjectiveSignals:
    duration_s = round(float(duration_s), 3)

    # 归一化为 (norm, start, end)，丢掉纯标点产生的空 token
    toks = [(n, w.start, w.end) for w in words if (n := _normalize(w.word))]
    norms = [n for n, _, _ in toks]
    word_count = len(toks)

    # —— 停顿：基于相邻词 gap（round 抹掉浮点误差再比阈值）——
    silence_count = hesitation_count = 0
    silence_total = hesitation_total = 0.0
    for (_, _, end), (_, nxt_start, _) in zip(toks, toks[1:]):
        gap = round(nxt_start - end, 6)
        if gap >= SILENCE_GAP_S:
            silence_count += 1
            silence_total += gap
            if gap >= HESITATION_GAP_S:
                hesitation_count += 1
                hesitation_total += gap
    silence_total = round(silence_total, 3)
    hesitation_total = round(hesitation_total, 3)
    silence_ratio = round(silence_total / duration_s, 4) if duration_s > 0 else 0.0

    # —— 语速：gross 含停顿；articulation 去掉静默时间，两者差即流利信号 ——
    minutes = duration_s / 60
    speaking_time = round(duration_s - silence_total, 3)
    gross_wpm = round(word_count / minutes, 1) if minutes > 0 else 0.0
    articulation_rate = (
        round(word_count / (speaking_time / 60), 1) if speaking_time > 0 and word_count else 0.0
    )

    # —— 填充词 ——
    filler_breakdown: dict[str, int] = {}
    for n in norms:
        if n in FILLERS:
            filler_breakdown[n] = filler_breakdown.get(n, 0) + 1
    filler_count = sum(filler_breakdown.values())
    filler_per_min = round(filler_count / minutes, 2) if minutes > 0 else 0.0

    # —— 自我更正（启发式，有误差）：相邻重复词 + 重复 bigram ——
    self_corrections: list[SelfCorrection] = []
    for a, b in zip(norms, norms[1:]):
        if a == b and a not in FILLERS:
            self_corrections.append(SelfCorrection("repeat_word", a))
    for i in range(len(norms) - 3):
        if norms[i] == norms[i + 2] and norms[i + 1] == norms[i + 3]:
            self_corrections.append(
                SelfCorrection("repeat_bigram", f"{norms[i]} {norms[i + 1]}")
            )

    # —— 词汇：TTR / 低频词 / 重复度（均不含填充词）——
    content = [n for n in norms if n not in FILLERS]
    distinct = set(content)
    distinct_word_count = len(distinct)
    ttr = round(distinct_word_count / len(content), 4) if content else 0.0
    low_freq = sum(1 for t in distinct if 0 < zipf_frequency(t, "en") < LOW_FREQ_ZIPF)
    counts: dict[str, int] = {}
    for n in content:
        counts[n] = counts.get(n, 0) + 1
    repeated = {
        k: v
        for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if v >= 2
    }

    return ObjectiveSignals(
        word_count=word_count,
        duration_s=duration_s,
        speaking_time_s=speaking_time,
        gross_wpm=gross_wpm,
        articulation_rate_wpm=articulation_rate,
        pauses=PauseSignals(
            silence_count=silence_count,
            silence_total_s=silence_total,
            hesitation_count=hesitation_count,
            hesitation_total_s=hesitation_total,
            silence_ratio=silence_ratio,
        ),
        filler_count=filler_count,
        filler_per_min=filler_per_min,
        filler_breakdown=filler_breakdown,
        self_corrections=self_corrections,
        self_corrections_heuristic=True,
        type_token_ratio=ttr,
        vocabulary_diversity_pct=round(ttr * 100, 1),
        distinct_word_count=distinct_word_count,
        low_frequency_word_count=low_freq,
        repeated_words=repeated,
    )
