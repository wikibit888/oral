"""GET /questions 题库单测——直接对真实静态库做 pin 测试（题库即契约）。"""

import pytest
from fastapi.testclient import TestClient

import app.api.questions as questions_module
from app.config import settings
from app.main import app

# 内容 pin：题库 id 集合即契约，误删改一张卡测试即红（review W4）
EXPECTED_P2_IDS = {f"p2-{i:02d}" for i in range(1, 9)}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    # lru_cache 是进程级共享态：显式清掉，声明本套测试对缓存的假设（review W2）
    questions_module._load_bank.cache_clear()
    with TestClient(app) as c:
        yield c


def test_p2_cue_cards_pin(client):
    # IELTS.md §2：cue card 静态精选库 8–10 张，每张话题 + 4 bullets
    r = client.get("/questions", params={"part": "p2"})
    assert r.status_code == 200
    cards = r.json()
    assert 8 <= len(cards) <= 10
    assert {c["id"] for c in cards} == EXPECTED_P2_IDS   # 内容 pin
    for c in cards:
        assert c["part"] == "p2"
        assert c["text"].startswith("Describe ")
        assert isinstance(c["bullets"], list) and len(c["bullets"]) == 4
        assert c["bullets"][3].startswith("and explain")   # 末条官方句式


@pytest.mark.parametrize("part", ["p1", "p3"])
def test_p1_p3_multi_questions(client, part):
    # 方式 B「一个 Part 多题」：p1/p3 至少 6 题、无 bullets
    r = client.get("/questions", params={"part": part})
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 6
    for q in items:
        assert q["part"] == part
        assert q["bullets"] is None
        assert q["text"].strip()


def test_ids_globally_unique(client):
    ids = []
    for part in ("p1", "p2", "p3"):
        ids += [q["id"] for q in client.get("/questions", params={"part": part}).json()]
    assert len(ids) == len(set(ids))


def test_tts_url_follows_file_existence(client, tmp_path, monkeypatch):
    # tts_url 按预生成文件存在性回填：无文件诚实 null（前端纯文字降级），
    # 有文件给 /static/tts 路径。指向 tmp 目录测，与本地 data/tts 状态无关。
    import app.api.questions as qmod

    monkeypatch.setattr(qmod, "TTS_DIR", tmp_path)
    first = client.get("/questions", params={"part": "p2"}).json()[0]
    assert first["tts_url"] is None

    (tmp_path / f"{first['id']}.wav").write_bytes(b"x")
    again = client.get("/questions", params={"part": "p2"}).json()[0]
    assert again["tts_url"] == f"/static/tts/{first['id']}.wav"


def test_invalid_or_missing_part_rejected(client):
    # 缺参与非法值统一中文 422（与项目其它端点文案风格一致，review W5）
    r_bad = client.get("/questions", params={"part": "p9"})
    assert r_bad.status_code == 422
    assert "part 必须是" in r_bad.json()["detail"]
    r_missing = client.get("/questions")
    assert r_missing.status_code == 422
    assert "part 必须是" in r_missing.json()["detail"]
