"""方式 A 模拟考抽题（F2）：以 topic 为子单位的真考流程组卷。

真考节奏（IELTS.md / PRD）：
- Part 1：8–10 个小问，**跨 2–3 个不同话题**（真考 P1 通常覆盖两三个日常话题）；
- Part 2：单张 cue card（一个话题）；
- Part 3：基于 Part 2 同话题延伸的抽象追问——靠 p2_3 捆绑天然同话题（无需关联推导）。

数据底座来自 `questions.load_exam_pools()`（PR1）：p1_topics 各含 questions，
p23_topics 各含 cue_card + 同话题 part3。本模块是 **bank + random 的纯函数**：
不读文件、不触网，便于单测（注入桩 bank 或 seed random 即可确定性断言）。

对小池稳健（回退精选库可能只有 1 个 p1 topic / part3 为空）：抽题量按池子大小
clamp，绝不越界、绝不崩——demo 至少要能开考。
"""

import random

from app.api import questions

# P1 目标题量区间（真考 P1 约 8–10 问）；池子不足时取全量、不报错
P1_MIN_QUESTIONS = 8
P1_MAX_QUESTIONS = 10
# P1 话题数区间（跨 2–3 个不同话题）；可用话题不足 2 个时用现有的
P1_MIN_TOPICS = 2
P1_MAX_TOPICS = 3


def _pick_p1_questions(p1_topics: list[dict]) -> list[dict]:
    """从 2–3 个不同话题里凑齐 8–10 个 P1 小问，尽量跨话题铺开。

    步骤：①随机选 2–3 个 DISTINCT 话题（池子不足按现有数 clamp）；②先从每个
    话题各取至少一个（保证"跨话题"而非全压在一个话题）；③仍不够目标量则从这些
    话题的剩余题里继续补，直到达标或选中话题的题被取尽。每条带上 topic_id 便于
    下游/测试交叉核对话题归属。
    """
    if not p1_topics:
        return []
    # 选多少个话题：目标 2–3，但不超过可用话题数（小池兜底）
    n_topics = min(random.randint(P1_MIN_TOPICS, P1_MAX_TOPICS), len(p1_topics))
    chosen = random.sample(p1_topics, n_topics)

    # 每个话题的题（打散内部顺序），按话题维护各自的"待取队列"
    pools: list[list[dict]] = []
    for topic in chosen:
        qs = [
            {"id": q["id"], "text": q["text"], "topic_id": topic["topic_id"]}
            for q in topic["questions"]
        ]
        random.shuffle(qs)
        if qs:
            pools.append(qs)
    if not pools:
        return []

    # 目标题量：8–10，但不超过选中话题的题总量（小池兜底）
    total_available = sum(len(p) for p in pools)
    target = min(random.randint(P1_MIN_QUESTIONS, P1_MAX_QUESTIONS), total_available)

    # 轮转跨话题取题（round-robin）：天然铺开，某话题题少则自动让位给其它话题
    selected: list[dict] = []
    while len(selected) < target and any(pools):
        for pool in pools:
            if pool:
                selected.append(pool.pop())
                if len(selected) >= target:
                    break
        # 清掉已取空的话题队列，避免空转
        pools = [p for p in pools if p]
    return selected


def pick_exam_set() -> dict:
    """组一场方式 A 模拟考的题：P1 跨话题题组 + P2 cue card + 其同话题 P3 追问。

    返回 `{"p1_questions": [...8–10...], "p2_card": {id,text,bullets}, "p3_questions": [...]}`：
    - p1_questions：跨 2–3 个不同话题抽样到 8–10 个 `{id, text, topic_id}`；
    - p2_card：随机一个 p23_topic 的 cue_card（即方式 A 既有的题卡，路径不变）；
    - p3_questions：同一个 p23_topic 的 part3（与 cue card 天然同话题 → P3 延伸 P2）。

    小池稳健：p23_topics 为空时 p2_card=None（理论上不会发生——回退库也有题卡）；
    选中话题 part3 为空（回退库）时 p3_questions=[]，考官按 persona 即兴。
    """
    pools = questions.load_exam_pools()
    p1_questions = _pick_p1_questions(pools.get("p1_topics", []))

    p23_topics = pools.get("p23_topics", [])
    if p23_topics:
        p23 = random.choice(p23_topics)
        card = p23["cue_card"]
        p2_card = {
            "id": card["id"],
            "text": card["text"],
            "bullets": card.get("bullets") or [],
        }
        p3_questions = [
            {"id": q["id"], "text": q["text"]} for q in p23.get("part3", [])
        ]
    else:
        p2_card = None
        p3_questions = []

    return {
        "p1_questions": p1_questions,
        "p2_card": p2_card,
        "p3_questions": p3_questions,
    }
