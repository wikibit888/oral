"""judge prompt 组装 + 报告 schema 单测（不调用 LLM）。"""

import pytest

from app.judge.prompt import build_judge_prompt, load_band_descriptors
from app.report import Report

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
