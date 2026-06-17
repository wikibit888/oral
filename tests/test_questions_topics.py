"""GET /questions/topics 单测（PR2 / F1 选题视图）——全量题目按 topic 分组返回。

季库每周刷新，故不 pin 具体 id；改 pin 结构契约（part 回填、topic 形状、p2 单卡）
与下游约束（题 id 必在该 part 的 _load_bank 池内）+ tts_url 文件存在性回填 + 中文 422。
"""

import pytest
from fastapi.testclient import TestClient

import app.api.questions as questions_module
from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    # lru_cache 是进程级共享态：显式清掉，声明本套测试对缓存的假设
    questions_module._load_raw.cache_clear()
    with TestClient(app) as c:
        yield c


# ---- 200：每个 Part 的分组形状契约 ----

@pytest.mark.parametrize("part", ["p1", "p2", "p3"])
def test_topics_grouped_shape(client, part):
    body = client.get("/questions/topics", params={"part": part}).json()
    assert body["part"] == part
    topics = body["topics"]
    assert topics, f"{part} 应有非空 topics"
    bank_ids = {q["id"] for q in questions_module._load_bank()[part]}
    for t in topics:
        assert t["topic_id"]
        assert t["title"]
        assert t["questions"], "topic 至少一题"
        for q in t["questions"]:
            assert q["part"] == part            # part 正确回填
            assert q["id"] in bank_ids          # 选题视图的题来自该 part 题池


# ---- p2：每 topic 恰一张题卡，且带 bullets 列表 ----

def test_p2_one_card_with_bullets(client):
    topics = client.get("/questions/topics", params={"part": "p2"}).json()["topics"]
    for t in topics:
        assert len(t["questions"]) == 1
        card = t["questions"][0]
        assert isinstance(card["bullets"], list)


# ---- p1/p3：bullets 为 null ----

@pytest.mark.parametrize("part", ["p1", "p3"])
def test_p1_p3_bullets_null(client, part):
    topics = client.get("/questions/topics", params={"part": part}).json()["topics"]
    for t in topics:
        for q in t["questions"]:
            assert q["bullets"] is None


# ---- tts_url：随预生成音频文件存在性切换 ----

def test_tts_url_follows_file_existence(client, tmp_path, monkeypatch):
    monkeypatch.setattr(questions_module, "TTS_DIR", tmp_path)
    body = client.get("/questions/topics", params={"part": "p1"}).json()
    first = body["topics"][0]["questions"][0]
    assert first["tts_url"] is None
    # 落文件后无需重启，stat 实时切换为非 null
    (tmp_path / f"{first['id']}.wav").write_bytes(b"x")
    again = client.get("/questions/topics", params={"part": "p1"}).json()
    flipped = again["topics"][0]["questions"][0]
    assert flipped["id"] == first["id"]
    assert flipped["tts_url"] == f"/static/tts/{first['id']}.wav"


# ---- 422：缺参与非法值，中文文案 ----

def test_invalid_part_rejected(client):
    r = client.get("/questions/topics", params={"part": "p9"})
    assert r.status_code == 422
    assert "part 必须是" in r.json()["detail"]


def test_missing_part_rejected(client):
    r = client.get("/questions/topics")
    assert r.status_code == 422
    assert "part 必须是" in r.json()["detail"]
