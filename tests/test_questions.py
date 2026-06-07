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


def test_p2_bank_pin_and_single_card_sample(client):
    # IELTS.md §2：cue card 静态精选库 8–10 张（题库即契约，pin 在 _load_bank 层）；
    # API 每场只发 1 张（对齐拍板 D1：单卡长谈，弃多卡连录）
    bank = questions_module._load_bank()["p2"]
    assert 8 <= len(bank) <= 10
    assert {c["id"] for c in bank} == EXPECTED_P2_IDS   # 内容 pin
    for c in bank:
        assert c["text"].startswith("Describe ")
        assert isinstance(c["bullets"], list) and len(c["bullets"]) == 4
        assert c["bullets"][3].startswith("and explain")   # 末条官方句式

    r = client.get("/questions", params={"part": "p2"})
    assert r.status_code == 200
    cards = r.json()
    assert len(cards) == 1                               # 每场一张
    assert cards[0]["id"] in EXPECTED_P2_IDS             # 抽自题池
    assert cards[0]["part"] == "p2"
    assert len(cards[0]["bullets"]) == 4


@pytest.mark.parametrize("part", ["p1", "p3"])
def test_p1_p3_sample_five(client, part):
    # 对齐拍板 D2：p1/p3 每场随机抽 5（live persona "about four or five questions"），
    # 题库（≥6 题）作随机池
    bank = questions_module._load_bank()[part]
    assert len(bank) >= 6
    r = client.get("/questions", params={"part": part})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 5
    bank_ids = {q["id"] for q in bank}
    for q in items:
        assert q["id"] in bank_ids                       # 抽自题池
        assert q["part"] == part
        assert q["bullets"] is None
        assert q["text"].strip()
    assert len({q["id"] for q in items}) == 5            # 同场不重复


def test_sampling_varies_across_requests(client):
    # 随机池语义：多次请求 p2 至少抽到 2 张不同的卡（8 张池、20 次试，
    # 全同概率 8^-19，准确定性）
    seen = {client.get("/questions", params={"part": "p2"}).json()[0]["id"] for _ in range(20)}
    assert len(seen) >= 2


def test_ids_globally_unique(client):
    ids = []
    for part in ("p1", "p2", "p3"):
        ids += [q["id"] for q in client.get("/questions", params={"part": part}).json()]
    assert len(ids) == len(set(ids))


def test_tts_url_follows_file_existence(client, tmp_path, monkeypatch):
    # tts_url 按预生成文件存在性回填：无文件诚实 null（前端纯文字降级），
    # 有文件给 /static/tts 路径。指向 tmp 目录测，与本地 data/tts 状态无关。
    # 抽样改打桩取首张：两次请求必须同一张卡才能断言回填翻转
    import app.api.questions as qmod

    monkeypatch.setattr(qmod, "TTS_DIR", tmp_path)
    monkeypatch.setattr(qmod.random, "sample", lambda pop, k: list(pop)[:k])
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


def test_bank_ids_globally_unique_at_load():
    # 抽样后 API 层不再全量过 24 题——银行级唯一性在 _load_bank 层钉死（review W1）
    all_ids = [
        q["id"] for part in ("p1", "p2", "p3")
        for q in questions_module._load_bank()[part]
    ]
    assert len(all_ids) == len(set(all_ids)) == 24
