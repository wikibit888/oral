"""GET /questions 题库单测——季题库(topic 分组)结构契约 + PR2/PR3 取数视图 + 回退。

季库每周刷新,故不再 pin 具体 id;改 pin 结构不变量(形状/全局唯一/文件名安全)
与下游契约(load_topics 选题视图、load_exam_pools 抽题池、P2↔P3 同 topic 关联)。
"""

import re

import pytest
from fastapi.testclient import TestClient

import app.api.questions as questions_module
from app.config import settings
from app.main import app

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # 文件名安全:既进 question_id 又进 {id}.wav


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    # lru_cache 是进程级共享态:显式清掉,声明本套测试对缓存的假设
    questions_module._load_raw.cache_clear()
    with TestClient(app) as c:
        yield c


# ---- 扁平题库(向后兼容层)结构契约 ----

def test_bank_shape_and_ids_safe():
    bank = questions_module._load_bank()
    assert set(bank) == {"p1", "p2", "p3"}
    all_ids = []
    for part in ("p1", "p2", "p3"):
        assert bank[part], f"{part} 题池不应为空"
        for q in bank[part]:
            assert q["part"] == part
            assert q["text"].strip()
            assert _ID_RE.match(q["id"]), f"非文件名安全 id: {q['id']}"
            all_ids.append(q["id"])
    # 全局唯一(抽样不再保证,银行级钉死)
    assert len(all_ids) == len(set(all_ids))
    # p2 是题卡:带 bullets 字段(季库 You should say 拆出,可能为空 list)
    for card in bank["p2"]:
        assert isinstance(card.get("bullets"), list)


def test_p2_cards_have_describe_or_bullets():
    # 题卡来源 = questions[0] 含 "describe a/.." 或 "you should say:";二者必居其一
    for card in questions_module._load_bank()["p2"]:
        text = card["text"].lower()
        assert text.startswith("describe ") or card["bullets"], card["id"]


# ---- GET /questions 抽样行为(沿用 5/1/5,只是池更大) ----

@pytest.mark.parametrize("part", ["p1", "p3"])
def test_p1_p3_sample_five(client, part):
    bank_ids = {q["id"] for q in questions_module._load_bank()[part]}
    items = client.get("/questions", params={"part": part}).json()
    assert len(items) == 5
    assert len({q["id"] for q in items}) == 5  # 同场不重复
    for q in items:
        assert q["id"] in bank_ids
        assert q["part"] == part
        assert q["bullets"] is None


def test_p2_single_card(client):
    cards = client.get("/questions", params={"part": "p2"}).json()
    assert len(cards) == 1
    assert cards[0]["part"] == "p2"
    assert isinstance(cards[0]["bullets"], list)


def test_sampling_varies_across_requests(client):
    seen = {client.get("/questions", params={"part": "p1"}).json()[0]["id"] for _ in range(20)}
    assert len(seen) >= 2


def test_invalid_or_missing_part_rejected(client):
    r_bad = client.get("/questions", params={"part": "p9"})
    assert r_bad.status_code == 422
    assert "part 必须是" in r_bad.json()["detail"]
    assert client.get("/questions").status_code == 422


def test_tts_url_follows_file_existence(client, tmp_path, monkeypatch):
    import app.api.questions as qmod

    monkeypatch.setattr(qmod, "TTS_DIR", tmp_path)
    monkeypatch.setattr(qmod.random, "sample", lambda pop, k: list(pop)[:k])
    first = client.get("/questions", params={"part": "p2"}).json()[0]
    assert first["tts_url"] is None
    (tmp_path / f"{first['id']}.wav").write_bytes(b"x")
    again = client.get("/questions", params={"part": "p2"}).json()[0]
    assert again["tts_url"] == f"/static/tts/{first['id']}.wav"


# ---- PR2 契约:load_topics 选题视图 ----

@pytest.mark.parametrize("part", ["p1", "p2", "p3"])
def test_load_topics_grouped(part):
    questions_module._load_raw.cache_clear()
    topics = questions_module.load_topics(part)
    assert topics, f"{part} 应有 topic"
    bank_ids = {q["id"] for q in questions_module._load_bank()[part]}
    for t in topics:
        assert t["topic_id"] and t["title"]
        assert t["questions"], "topic 至少一题"
        for q in t["questions"]:
            assert q["id"] in bank_ids  # 选题视图的题来自该 part 题池
    # p2 每 topic 恰一张题卡
    if part == "p2":
        assert all(len(t["questions"]) == 1 for t in topics)


# ---- PR3 契约:load_exam_pools 抽题池 + P2↔P3 同 topic 关联 ----

def test_load_exam_pools_linkage():
    questions_module._load_raw.cache_clear()
    pools = questions_module.load_exam_pools()
    # F2 需 P1 从 2~3 个不同 topic 抽题:话题池至少 3 个
    assert len(pools["p1_topics"]) >= 3
    for t in pools["p1_topics"]:
        assert t["topic_id"] and t["questions"]
    # P2/3 捆绑:每 topic 一张题卡 + 同话题 part3(题卡与追问同 topic_id 下)
    assert pools["p23_topics"]
    for t in pools["p23_topics"]:
        assert t["cue_card"]["id"].startswith("s-p2-")
        assert isinstance(t["part3"], list)
        for q in t["part3"]:
            assert q["id"].startswith("s-p3-")
    # 至少一个话题真的带 part3 追问(P3 延伸 P2 的前提)
    assert any(t["part3"] for t in pools["p23_topics"])


# ---- 回退:主文件不可读时回退精选库 ----

def test_fallback_when_primary_unreadable(tmp_path, monkeypatch):
    import app.api.questions as qmod

    monkeypatch.setattr(qmod, "QUESTIONS_PATH", tmp_path / "missing.json")  # 主文件缺失
    qmod._load_raw.cache_clear()
    raw = qmod._load_raw()
    assert not qmod._is_season_schema(raw)  # 回退是旧精选 schema
    bank = qmod._load_bank()
    assert {c["id"] for c in bank["p2"]} == {f"p2-{i:02d}" for i in range(1, 9)}
    # 回退下选题视图仍可用(合成兜底 topic)
    assert qmod.load_topics("p1")
    qmod._load_raw.cache_clear()
