"""judge prompt 组装：把 transcript + 客观信号 + 模式 prompt 拼成一次调用的内容。

雅思注入官方 band descriptor；情景注入 case prompt 且禁 band。grounding 规则
（evidence 逐字、防幻觉、信号是输入非成绩）所有模式共享。temperature=0 与结构化
输出 schema 在实际调用处（PR-4b）施加。
"""

import json
from pathlib import Path
from typing import Mapping

_DESCRIPTORS_PATH = Path(__file__).parent / "band_descriptors.md"


def load_band_descriptors() -> str:
    return _DESCRIPTORS_PATH.read_text(encoding="utf-8")


GROUNDING_RULES = """\
评分铁律（务必遵守）：
1. 证据必须逐字引用考生原话（来自下方 transcript）。引不出原话作证据，就不要下该项判断。
2. 不得编造、不得脑补。区分「ASR 没听清」与「考生真说错」——存疑时不扣分。
3. 客观信号是判断的输入 / 佐证，不是最终成绩；不要把任何「像母语度」分数直接当发音 band。
4. 保持确定性与保守：同一段录音重复评分应高度一致。\
"""

DIAGNOSTIC_INSTRUCTIONS = """\
诊断层（所有模式都要产出，填入 diagnostics）：
- common_patterns：口头禅 / 重复用语 + 出现次数。
- syntactic_analysis：句式单一性 observation + 改写方向 suggestion。
- frequent_errors：高频错误，带 category（grammar / vocabulary / ...）、desc、count。
- fossilized_errors：反复犯的硬错，occurrences 列逐字原话。
- self_corrections：自我更正的正向例子（initial → corrected，逐字）。
- top_priorities：3–5 条最关键问题，每条 title + severity(high/medium/low) + explanation + examples(逐字) + quick_fix。
- rewrites：挑 2–3 段考生说过的不够好的话，并排给出 {original(逐字), rewrite, reason}。\
"""

SCENARIO_INSTRUCTIONS = """\
模式：情景对话。**不出 band、不出 overall_band**（band 是雅思 rubric 产物，套到情景会错配）。
dimensions 与 overall_band 必须为 null；只产出诊断层 + 共享的客观流利度指标。\
"""


def _ielts_instructions() -> str:
    return f"""\
模式：雅思（IELTS Speaking）。按官方四维给 band，并产出诊断层。

四维（填入 dimensions，每维：band + evidence[逐字] + descriptor_match + suggestions）：
- fluency_coherence
- lexical_resource
- grammatical_range_accuracy
- pronunciation —— 按**可懂度（intelligibility）**判，不按像母语度；从音频听重音 / 连读 / 语调，结合停顿信号 grounding。

对照下列官方 band descriptor 打分，descriptor_match 写明「命中 band X 的哪条、卡在 band X+1 的哪条」：

{load_band_descriptors()}

overall_band 留空（由系统按四维平均确定性聚合，judge 不要自行计算）。\
"""


def build_judge_prompt(
    mode: str,
    *,
    transcript_text: str,
    signals: Mapping,
    sub_mode: str | None = None,
    scenario_case: str | None = None,
    case_prompt: str | None = None,
) -> str:
    """组装一次 judge 调用的内容 prompt。

    mode='ielts' 注入 band descriptor；mode='scenario' 注入 case prompt 且禁 band。
    case_prompt 为情景 case 侧重段（P5 写数据文件传入）；缺省时给占位提示。
    """
    if mode == "ielts":
        mode_section = _ielts_instructions()
    elif mode == "scenario":
        focus = case_prompt or f"[CASE 侧重：{scenario_case} —— 详细 case prompt 在 P5 注入]"
        mode_section = f"{SCENARIO_INSTRUCTIONS}\n\nCase 侧重：\n{focus}"
    else:
        raise ValueError(f"未知 mode: {mode!r}")

    signals_json = json.dumps(dict(signals), ensure_ascii=False, indent=2)

    return "\n".join(
        [
            "你是严格、专业的英语口语考官 / 诊断教练。一次性产出整份结构化报告。",
            "",
            GROUNDING_RULES,
            "",
            mode_section,
            "",
            DIAGNOSTIC_INSTRUCTIONS,
            "",
            "—— 考生 transcript（逐字，证据只能引自这里）——",
            transcript_text,
            "",
            "—— 客观信号（确定性，作为判断输入 / 佐证）——",
            signals_json,
        ]
    )
