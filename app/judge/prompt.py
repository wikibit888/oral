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

# 方式 B 各 Part 的诊断侧重（IELTS.md §3：分模块练习，按 Part 特性给针对性反馈）
MODULE_FOCUS = {
    "module_p1": (
        "Part 1（日常问答）侧重：是否直接回应问题、短答后能否自然扩展 2–3 句、"
        "日常话题词汇的准确与自然度、问答节奏（避免背诵感）。"
    ),
    "module_p2": (
        "Part 2（cue card 长谈）侧重：组织结构（开头点题—按 bullets 展开—收尾）、"
        "1–2 分钟持续输出的连贯性（连接词多样性、避免 'and then' 串句）、"
        "话题展开充分度、长独白中的时态一致。"
    ),
    "module_p3": (
        "Part 3（抽象讨论）侧重：论证结构（观点—理由—例证）、抽象与学术词汇、"
        "复杂句式（条件句 / 让步 / 定语从句）的准确使用、观点深度与平衡性。"
    ),
}


def _ielts_b_instructions(sub_mode: str) -> str:
    if sub_mode not in MODULE_FOCUS:   # 防御：仅 build_judge_prompt 守门，直调要快败
        raise ValueError(f"非方式 B 的 sub_mode: {sub_mode!r}")
    return f"""\
模式：雅思方式 B（分模块练习，{sub_mode}）。**最终报告不展示数字 band**——
分模块的单 Part 样本碎，数字 band 解释力弱，只给 descriptor 对齐的诊断反馈。

四维仍按官方 descriptor 照常判定并填入 dimensions（band + evidence[逐字] +
descriptor_match + suggestions）——这是**内部诊断依据**，系统会在最终报告里
移除数字、只保留诊断层；若录音完全不可评（静音 / 非英语），dimensions 留空。
pronunciation 按**可懂度（intelligibility）**从音频判，不按像母语度。

诊断层是用户唯一可见的反馈，必须落到本 Part 的侧重点上：
{MODULE_FOCUS[sub_mode]}
top_priorities / suggestions 里可以引用 descriptor 的语言定位表现
（如「fluency 表现接近 'willing to speak at length' 的水平，但…」）。
dimensions 里的数字仅供系统内部使用，**绝不得出现在 top_priorities / suggestions /
explanation 等任何诊断文本字段中**。

对照下列官方 band descriptor 做诊断对齐：

{load_band_descriptors()}\
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

    mode='ielts' 按 sub_mode 分流：exam（方式 A）注入 descriptor 出四维 band；
    module_pX（方式 B）注入 descriptor 做诊断对齐 + Part 侧重，**不出数字 band**
    （四维仍内部判定供系统检测 unscorable，最终报告由 run_judge 置空）。
    mode='scenario' 注入 case prompt 且禁 band。
    case_prompt 为情景 case 侧重段（P5 写数据文件传入）；缺省时给占位提示。
    """
    if mode == "ielts":
        if sub_mode in MODULE_FOCUS:
            mode_section = _ielts_b_instructions(sub_mode)
        else:
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
