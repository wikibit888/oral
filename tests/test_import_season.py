"""scripts/import_ielts_season.py 单测:去壳 / Part 推断 / 题卡拆分 / id 安全。"""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "import_ielts_season.py"
_spec = importlib.util.spec_from_file_location("import_ielts_season", _PATH)
imp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(imp)


def test_deshell_strips_js_wrapper():
    topics = imp._deshell('const topics = [{"number":"Topic 1: X","questions":["a?"]}];')
    assert topics == [{"number": "Topic 1: X", "questions": ["a?"]}]


def test_is_part2_detection():
    assert imp._is_part2(["Describe a person you admire."])
    assert imp._is_part2(["Talk about it. You should say: who, why"])
    assert not imp._is_part2(["Do you like music?"])


def test_split_cue_card():
    main, bullets = imp.split_cue_card(
        "Describe a job. You should say: What it is, Where it is, And explain why."
    )
    assert main == "Describe a job."
    assert bullets == ["What it is", "Where it is", "And explain why."]
    # 无 "You should say:" → 整句作主干,bullets 空
    main2, bullets2 = imp.split_cue_card("Describe a place.")
    assert main2 == "Describe a place." and bullets2 == []


def test_convert_shape_ids_and_linkage():
    topics = [
        {"number": "Topic 1: Music", "questions": ["Do you like music?", "Why?"]},
        {
            "number": "Topic 2: A job",
            "questions": [
                "Describe a job. You should say: what, where, And explain why.",
                "Is salary important?",
                "What jobs are popular?",
            ],
        },
    ]
    bank = imp.convert(topics, "may-aug-2026")
    assert bank["season"] == "may-aug-2026"
    # P1 话题展开成题
    assert bank["p1"][0]["topic_id"] == "p1-t01"
    assert [q["id"] for q in bank["p1"][0]["questions"]] == ["s-p1-t01-q01", "s-p1-t01-q02"]
    # P2/3 捆绑:题卡 + 同 topic 的 part3
    t = bank["p2_3"][0]
    assert t["topic_id"] == "t01"
    assert t["cue_card"]["id"] == "s-p2-t01"
    assert t["cue_card"]["text"] == "Describe a job."
    assert t["cue_card"]["bullets"] == ["what", "where", "And explain why."]
    assert [q["id"] for q in t["part3"]] == ["s-p3-t01-q01", "s-p3-t01-q02"]
    imp.validate(bank)  # 不抛即通过(唯一 + 文件名安全)


def test_validate_rejects_dup_and_unsafe_ids():
    with pytest.raises(ValueError):
        imp.validate({"p1": [], "p2_3": []})  # p1/p2_3 空
    dup = {
        "p1": [{"topic_id": "p1-t01", "title": "X",
                "questions": [{"id": "dup", "text": "a"}, {"id": "dup", "text": "b"}]}],
        "p2_3": [{"topic_id": "t01", "title": "Y",
                  "cue_card": {"id": "s-p2-t01", "text": "Describe", "bullets": []}, "part3": []}],
    }
    with pytest.raises(ValueError):
        imp.validate(dup)
