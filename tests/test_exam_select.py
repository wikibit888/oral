"""方式 A 模拟考抽题（F2）单测：以 topic 为子单位组卷。

覆盖：P1 跨 2–3 个不同话题抽到 8–10 个、与 load_exam_pools 交叉核对（id/topic 归属）、
P2 cue card 形如 s-p2-*、P3 追问全 s-p3-* 且与 cue card 同话题（捆绑链路）、
小池/回退库桩（1 个 p1 话题、part3 为空）不崩边角。纯函数 + seed random 求确定性。
"""

import random

import pytest

from app.api import questions
from app.live import exam_select
from app.live.exam_select import pick_exam_set


def test_pick_exam_set_p1_spans_2_3_topics_and_8_10_questions():
    # 真季题库实跑：P1 题量落在 8–10，且来自 2–3 个不同话题
    random.seed(20260617)
    result = pick_exam_set()
    p1 = result["p1_questions"]
    assert 8 <= len(p1) <= 10
    topics = {q["topic_id"] for q in p1}
    assert 2 <= len(topics) <= 3


def test_pick_exam_set_p1_questions_match_their_topics():
    # 交叉核对：每个 P1 题确属其标注 topic_id 的话题（id 在该话题 questions 内）
    random.seed(1)
    pools = questions.load_exam_pools()
    by_topic = {t["topic_id"]: {q["id"] for q in t["questions"]} for t in pools["p1_topics"]}
    result = pick_exam_set()
    for q in result["p1_questions"]:
        assert q["topic_id"] in by_topic
        assert q["id"] in by_topic[q["topic_id"]]
    # 题不重复（跨话题铺开不应取到同一题两次）
    ids = [q["id"] for q in result["p1_questions"]]
    assert len(ids) == len(set(ids))


def test_pick_exam_set_p2_card_and_p3_same_topic_linkage():
    # P2 cue card 形如 s-p2-*；P3 追问全 s-p3-* 且与 cue card 同一 topic（捆绑）
    random.seed(7)
    pools = questions.load_exam_pools()
    # 反查 cue_card.id → 该 topic 的 part3 id 集合，验证 p3 全部属同话题
    card_to_part3 = {
        t["cue_card"]["id"]: {q["id"] for q in t["part3"]} for t in pools["p23_topics"]
    }
    result = pick_exam_set()
    card = result["p2_card"]
    assert card["id"].startswith("s-p2-")
    assert "bullets" in card
    p3_ids = card_to_part3[card["id"]]
    assert result["p3_questions"], "真季库该话题应有 part3 追问"
    for q in result["p3_questions"]:
        assert q["id"].startswith("s-p3-")
        assert q["id"] in p3_ids            # 同话题链路：P3 延伸 P2


def test_pick_exam_set_p1_topics_count_clamped_to_pool(monkeypatch):
    # 话题数被 clamp 到可用话题数：只有 2 个话题时绝不试图选 3 个
    pool = {
        "p1_topics": [
            {"topic_id": "t-a", "title": "A", "questions": [
                {"id": "a1", "text": "qa1"}, {"id": "a2", "text": "qa2"},
                {"id": "a3", "text": "qa3"}, {"id": "a4", "text": "qa4"},
                {"id": "a5", "text": "qa5"},
            ]},
            {"topic_id": "t-b", "title": "B", "questions": [
                {"id": "b1", "text": "qb1"}, {"id": "b2", "text": "qb2"},
                {"id": "b3", "text": "qb3"}, {"id": "b4", "text": "qb4"},
                {"id": "b5", "text": "qb5"},
            ]},
        ],
        "p23_topics": [
            {"topic_id": "t-c", "title": "C",
             "cue_card": {"id": "s-p2-c", "text": "card c", "bullets": ["x"]},
             "part3": [{"id": "s-p3-c-1", "text": "fc1"}]},
        ],
    }
    monkeypatch.setattr(exam_select.questions, "load_exam_pools", lambda: pool)
    random.seed(3)
    result = pick_exam_set()
    topics = {q["topic_id"] for q in result["p1_questions"]}
    assert topics <= {"t-a", "t-b"}        # 只可能来自这 2 个话题
    assert 1 <= len(topics) <= 2


def test_pick_exam_set_fallback_tiny_pool_does_not_crash(monkeypatch):
    # 回退精选库桩：仅 1 个 p1 话题（题不足 8）、part3 为空——clamp + 不崩
    tiny = {
        "p1_topics": [
            {"topic_id": "fallback-p1", "title": "Part 1", "questions": [
                {"id": "f1", "text": "fq1"}, {"id": "f2", "text": "fq2"},
                {"id": "f3", "text": "fq3"},
            ]},
        ],
        "p23_topics": [
            {"topic_id": "fallback-s-p2-x", "title": "card x",
             "cue_card": {"id": "s-p2-x", "text": "card x", "bullets": []},
             "part3": []},
        ],
    }
    monkeypatch.setattr(exam_select.questions, "load_exam_pools", lambda: tiny)
    random.seed(0)
    result = pick_exam_set()
    # 题不足 8：全量取该话题的 3 题，不报错
    assert len(result["p1_questions"]) == 3
    assert {q["topic_id"] for q in result["p1_questions"]} == {"fallback-p1"}
    assert result["p2_card"]["id"] == "s-p2-x"
    assert result["p3_questions"] == []    # 回退库无 part3，考官即兴


def test_pick_exam_set_empty_pools_does_not_crash(monkeypatch):
    # 极端空池：p1/p23 全空——不崩，返回空 P1、p2_card=None、空 P3
    monkeypatch.setattr(
        exam_select.questions,
        "load_exam_pools",
        lambda: {"p1_topics": [], "p23_topics": []},
    )
    result = pick_exam_set()
    assert result["p1_questions"] == []
    assert result["p2_card"] is None
    assert result["p3_questions"] == []
