"""judge prompt 组装 + 报告 schema 单测（不调用 LLM）。"""

import pytest

from app.judge.prompt import build_judge_prompt, load_band_descriptors
from app.report import LiveCorrection, LiveFeedback, LiveTeaching, Report

SIGNALS = {"gross_wpm": 137.1, "type_token_ratio": 0.71, "filler_per_min": 17.14}
TRANSCRIPT = "I think science is mostly about curiosity."


def test_band_descriptors_loaded():
    md = load_band_descriptors()
    for dim in ("Fluency and Coherence", "Lexical Resource",
                "Grammatical Range and Accuracy", "Pronunciation"):
        assert dim in md


def test_ielts_prompt_injects_descriptor_and_grounding():
    p = build_judge_prompt("ielts", transcript_text=TRANSCRIPT, signals=SIGNALS, sub_mode="exam")
    # 注入官方 descriptor
    assert "IELTS Speaking Band Descriptors" in p
    # 四维齐全
    for key in ("fluency_coherence", "lexical_resource",
                "grammatical_range_accuracy", "pronunciation"):
        assert key in p
    # 发音按可懂度
    assert "可懂度" in p
    # grounding：evidence 逐字
    assert "逐字引用考生原话" in p
    # transcript 与客观信号都进了 prompt
    assert TRANSCRIPT in p
    assert "137.1" in p


def test_scenario_prompt_no_band_no_descriptor():
    p = build_judge_prompt("scenario", transcript_text=TRANSCRIPT, signals=SIGNALS, scenario_case="ordering")
    assert "不出 band" in p
    assert "ordering" in p
    # 情景不注入雅思 descriptor
    assert "IELTS Speaking Band Descriptors" not in p
    # case_prompt 缺省时给占位提示
    assert "P5" in p
    # 教练协议防失真：中文求助的乱码转写不计错误、不作证据（SCENARIO_CASE.md A 类）
    assert "不计入错误" in p


def test_scenario_prompt_no_rewrites_with_summary():
    """情景报告结构（用户决策 2026-06-07）：rewrites 留空 + 末尾 summary 总结。"""
    p = build_judge_prompt("scenario", transcript_text=TRANSCRIPT, signals=SIGNALS, scenario_case="ordering")
    assert "rewrites 留空列表" in p
    assert "先肯定" in p and "提升方向" in p     # summary 三要素：鼓励→问题→方向
    # 雅思侧：rewrites 仅雅思产出、summary 留 null
    ielts = build_judge_prompt("ielts", transcript_text=TRANSCRIPT, signals=SIGNALS, sub_mode="exam")
    assert "仅雅思产出" in ielts
    assert "雅思留 null" in ielts


def test_scenario_prompt_injects_live_feedback_block():
    """FC 反馈实录作输入材料注入：纠错对照 + 中文求助；无实录 / 空实录不注入。"""
    lf = LiveFeedback(
        corrections=[
            LiveCorrection(
                original="I want order pasta", fixed="I'd like to order pasta",
                note="politeness", spoken=True,
            )
        ],
        teachings=[
            LiveTeaching(
                kind="mixed_cn", chinese="意大利面", english="spaghetti",
                example="Could I get the spaghetti, please?",
            )
        ],
    )
    p = build_judge_prompt(
        "scenario", transcript_text=TRANSCRIPT, signals=SIGNALS,
        scenario_case="ordering", live_feedback=lf,
    )
    assert "会话内即时反馈实录" in p
    assert "语法纠错 1 条" in p and "I'd like to order pasta" in p
    assert "中文求助 1 条" in p and "「意大利面」 → spaghetti" in p
    assert "transcript 为准" in p              # 用途边界：证据引用仍只认 transcript
    # 不传 / 空实录都不注入
    p0 = build_judge_prompt("scenario", transcript_text=TRANSCRIPT, signals=SIGNALS, scenario_case="ordering")
    assert "会话内即时反馈实录" not in p0
    p1 = build_judge_prompt(
        "scenario", transcript_text=TRANSCRIPT, signals=SIGNALS,
        scenario_case="ordering", live_feedback=LiveFeedback(corrections=[], teachings=[]),
    )
    assert "会话内即时反馈实录" not in p1


def test_scenario_prompt_uses_case_prompt_when_given():
    p = build_judge_prompt(
        "scenario", transcript_text=TRANSCRIPT, signals=SIGNALS,
        scenario_case="ordering", case_prompt="看点单流程是否说清：菜品、数量、忌口。",
    )
    assert "看点单流程是否说清" in p
    assert "P5" not in p


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        build_judge_prompt("toefl", transcript_text=TRANSCRIPT, signals=SIGNALS)


def test_language_rules_injected_all_modes():
    """语言规范段三种模式都注入：引用一字不改 / rewrite 纯英文 / 解释一律中文。"""
    prompts = [
        build_judge_prompt("ielts", transcript_text=TRANSCRIPT, signals=SIGNALS, sub_mode="exam"),
        build_judge_prompt("ielts", transcript_text=TRANSCRIPT, signals=SIGNALS, sub_mode="module_p1"),
        build_judge_prompt("ielts", transcript_text=TRANSCRIPT, signals=SIGNALS, sub_mode="module_p2"),
        build_judge_prompt("ielts", transcript_text=TRANSCRIPT, signals=SIGNALS, sub_mode="module_p3"),
        build_judge_prompt("scenario", transcript_text=TRANSCRIPT, signals=SIGNALS, scenario_case="ordering"),
    ]
    for p in prompts:
        assert "输出语言规范" in p
        assert "一字不改" in p      # 录音引用保持原文
        assert "纯英文" in p        # rewrite 英文示范句
        assert "一律用中文" in p    # 解释性字段中文


# —— 报告 schema —— #
_DIAGNOSTICS = {
    "common_patterns": [{"pattern": "You know", "count": 2}],
    "syntactic_analysis": {"observation": "6/9 主句以 I+动词 开头", "suggestion": "试介词短语开头"},
    "frequent_errors": [{"category": "grammar", "desc": "三单一致", "count": 1}],
    "fossilized_errors": [{"desc": "主谓一致反复", "occurrences": ["she teach Chinese"]}],
    "self_corrections": [{"initial": "we we all", "corrected": "we all need to learn"}],
    "vocabulary_diversity_pct": 44.0,
    "top_priorities": [{
        "title": "三单动词一致", "severity": "high", "explanation": "...",
        "examples": ["She teach Chinese"], "quick_fix": "加 -s",
    }],
    "rewrites": [{"original": "I think science is curiosity",
                  "rewrite": "Science is driven by curiosity", "reason": "更简洁"}],
}
_SUMMARY = {"speaking_time_s": 47, "sessions": 1, "recordings": 1}


def test_scenario_report_has_no_band():
    r = Report(practice_summary=_SUMMARY, diagnostics=_DIAGNOSTICS)
    assert r.dimensions is None
    assert r.overall_band is None
    assert r.diagnostics.vocabulary_diversity_pct == 44.0


def test_ielts_report_validates():
    dim = {"band": 6.5, "evidence": ["I think science is curiosity"],
           "descriptor_match": "命中 6、卡在 7", "suggestions": ["多用连接词"]}
    r = Report(
        practice_summary=_SUMMARY,
        dimensions={
            "fluency_coherence": dim, "lexical_resource": dim,
            "grammatical_range_accuracy": dim, "pronunciation": dim,
        },
        overall_band=6.5,
        diagnostics=_DIAGNOSTICS,
    )
    assert r.dimensions.pronunciation.band == 6.5
    assert r.overall_band == 6.5


def test_band_out_of_range_rejected():
    with pytest.raises(ValueError):
        Report(
            practice_summary=_SUMMARY,
            dimensions={
                "fluency_coherence": {"band": 12, "evidence": [], "descriptor_match": "", "suggestions": []},
                "lexical_resource": {"band": 6, "evidence": [], "descriptor_match": "", "suggestions": []},
                "grammatical_range_accuracy": {"band": 6, "evidence": [], "descriptor_match": "", "suggestions": []},
                "pronunciation": {"band": 6, "evidence": [], "descriptor_match": "", "suggestions": []},
            },
            diagnostics=_DIAGNOSTICS,
        )


# —— 方式 B（module_pX）按 Part 侧重 + 不出数字 band —— #
def test_ielts_b_prompt_descriptor_aligned_no_numeric_band():
    from app.judge.prompt import build_judge_prompt

    p = build_judge_prompt(
        "ielts", transcript_text="t", signals={}, sub_mode="module_p2",
    )
    assert "方式 B" in p
    assert "不展示数字 band" in p
    assert "cue card 长谈" in p                       # Part 侧重注入
    assert "Fluency" in p or "fluency" in p          # descriptor 仍注入（诊断对齐）
    assert "内部诊断依据" in p


def test_ielts_b_each_part_has_distinct_focus():
    from app.judge.prompt import build_judge_prompt

    p1 = build_judge_prompt("ielts", transcript_text="t", signals={}, sub_mode="module_p1")
    p3 = build_judge_prompt("ielts", transcript_text="t", signals={}, sub_mode="module_p3")
    assert "日常问答" in p1 and "抽象讨论" not in p1
    assert "抽象讨论" in p3 and "日常问答" not in p3


def test_ielts_exam_prompt_unchanged_band_flow():
    from app.judge.prompt import build_judge_prompt

    p = build_judge_prompt("ielts", transcript_text="t", signals={}, sub_mode="exam")
    assert "按官方四维给 band" in p
    assert "方式 B" not in p


def test_exam_prompt_explains_exam_mechanics_b_does_not():
    # 方式 B 对齐批次 A3（2026-06-07）：考试机制免责（2 分钟切断/软探询非考生失误）
    # 只进 exam 分支——B 无 live 切断机制，注入即幻觉式免责（交叉复核警示）
    from app.judge.prompt import build_judge_prompt

    exam = build_judge_prompt("ielts", transcript_text="t", signals={}, sub_mode="exam")
    assert "礼貌\n打断" in exam or "礼貌打断" in exam.replace("\n", "")
    assert "anything else you would like to add" in exam
    for sub in ("module_p1", "module_p2", "module_p3"):
        b = build_judge_prompt("ielts", transcript_text="t", signals={}, sub_mode=sub)
        assert "礼貌打断" not in b.replace("\n", "")
        assert "anything else you would like to add" not in b


def test_module_p2_focus_mentions_long_turn_duration():
    # 方式 B 对齐批次 A2：单卡长谈语义 + speaking_time_s 对照 1–2 分钟评达标度
    from app.judge.prompt import build_judge_prompt

    p = build_judge_prompt("ielts", transcript_text="t", signals={}, sub_mode="module_p2")
    flat = p.replace("\n", "")
    assert "仅一张卡一次长谈" in flat
    assert "speaking_time_s" in flat
    assert "不作为语言错误证据" in flat
