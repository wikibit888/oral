"""雅思 overall_band 聚合（确定性，judge 不自算）。

四维平均后四舍五入到最近 0.5：.25 进 .5、.75 进整（PRD §6.2）。
用 floor(x*2 + 0.5)/2 实现 round-half-up，避开 Python round() 的银行家舍入。
"""

import math

from app.report import Dimensions


def round_to_half(value: float) -> float:
    return math.floor(value * 2 + 0.5) / 2


def aggregate_overall_band(dims: Dimensions) -> float:
    bands = [
        dims.fluency_coherence.band,
        dims.lexical_resource.band,
        dims.grammatical_range_accuracy.band,
        dims.pronunciation.band,
    ]
    return round_to_half(sum(bands) / len(bands))
