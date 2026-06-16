"""方式 B 题库入口：GET /questions?part=p1|p2|p3（SCHEMA §6.5 / IELTS.md §3）。

题目来自静态库 `data/questions.json`（p2 同时充当方式 A 的 cue card 库），
进程内缓存一次；`tts_url` 按预生成音频文件（data/tts/{id}.wav，TTS 项产出）
的存在性回填——音频未生成时为 null，前端降级为纯文字读题。

每请求随机抽样（方式 B 对齐拍板 D1/D2，2026-06-07）：对齐 live 考试节奏——
p1/p3 每场从题库随机抽 5（live persona "about four or five questions"）、
p2 每场 1 张 cue card（真考/live 同款单卡长谈，弃多卡连录）；题库全量保留作
随机池（多次练习不重样）。方式 A 的 cue card 直读 _load_bank 不受影响。
"""

import json
import random
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["questions"])

VALID_PARTS = {"p1", "p2", "p3"}
# 每场抽题量：p1/p3 五问对齐 live 节奏；p2 单卡 = 一次长谈
SAMPLE_SIZE = {"p1": 5, "p2": 1, "p3": 5}

# 路径用模块常量（非 settings）：静态资源位置是仓库布局的一部分，不随环境变化。
# 以本文件位置锚定仓库根（app/api/ 上两级），不依赖进程 cwd（review W1）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = _REPO_ROOT / "data" / "questions.json"
# 回退精选库（§7 新库优先、精选回退）：主文件损坏/缺失时兜底，保 demo 不崩
FALLBACK_PATH = _REPO_ROOT / "data" / "questions_fallback.json"
TTS_DIR = _REPO_ROOT / "data" / "tts"
TTS_URL_PREFIX = "/static/tts"


class Question(BaseModel):
    id: str
    part: str                       # p1 | p2 | p3
    text: str
    bullets: list[str] | None = None   # 仅 p2 cue card（4 条）
    tts_url: str | None = None      # 预生成 TTS；未生成为 null（前端纯文字降级）


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    """读题库主文件；损坏/缺失则回退精选库（§7 新库优先、精选回退）。

    返回原始 dict（季 schema 或旧精选 schema 二者之一），缓存于进程生命周期。
    两库均不可读才抛——demo 至少要有题。
    """
    for path in (QUESTIONS_PATH, FALLBACK_PATH):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    raise RuntimeError("题库主文件与回退文件均不可读")


def _is_season_schema(raw: dict) -> bool:
    """季 schema 以 topic 分组（含 p2_3 捆绑）；旧精选 schema 是扁平 p1/p2/p3 列表。"""
    return "p2_3" in raw


def _load_bank() -> dict[str, list[dict]]:
    """按 part 分组的扁平题库（向后兼容：GET /questions 抽样、_pick_cue_card、TTS 预生成）。

    季 schema 在此摊平（p1 话题展开成题、p2_3 拆出题卡与 part3）；旧精选 schema
    直接注入 part。part 字段加载时注入每条，下游不依赖调用方传入（review S2）。
    """
    raw = _load_raw()
    if _is_season_schema(raw):
        return {
            "p1": [{**q, "part": "p1"} for t in raw["p1"] for q in t["questions"]],
            "p2": [{**t["cue_card"], "part": "p2"} for t in raw["p2_3"]],
            "p3": [{**q, "part": "p3"} for t in raw["p2_3"] for q in t["part3"]],
        }
    return {part: [{**item, "part": part} for item in raw.get(part, [])] for part in VALID_PARTS}


def load_topics(part: str) -> list[dict]:
    """选题 UI（方式 B / F1）用：该 Part 的 topic 列表，每 topic 含可勾选 questions。

    p1：topic → 多个小问题；p2：topic → [题卡（含 bullets）]；p3：topic → part3 追问。
    回退精选库无 topic 信息时，合成单一兜底 topic，保选题页不空白。
    """
    raw = _load_raw()
    if _is_season_schema(raw):
        if part == "p1":
            return [
                {"topic_id": t["topic_id"], "title": t["title"], "questions": t["questions"]}
                for t in raw["p1"]
            ]
        if part == "p2":
            return [
                {"topic_id": t["topic_id"], "title": t["title"], "questions": [t["cue_card"]]}
                for t in raw["p2_3"]
            ]
        if part == "p3":
            return [
                {"topic_id": t["topic_id"], "title": t["title"], "questions": t["part3"]}
                for t in raw["p2_3"]
                if t["part3"]
            ]
        return []
    items = _load_bank().get(part, [])
    return [{"topic_id": f"fallback-{part}", "title": f"Part {part[-1]}", "questions": items}] if items else []


def load_exam_pools() -> dict:
    """方式 A 模拟考（F2）抽题用：P1 话题池 + P2/3 捆绑池（题卡 + 其 part3 追问）。

    P2↔P3 以 topic 为单位天然捆绑——抽一个 p2_3 topic 即得题卡 + 同话题追问，
    满足"P3 基于 P2 话题延伸"。回退精选库无关联时 part3 为空（考官即兴）。
    """
    raw = _load_raw()
    if _is_season_schema(raw):
        return {
            "p1_topics": [
                {"topic_id": t["topic_id"], "title": t["title"], "questions": t["questions"]}
                for t in raw["p1"]
            ],
            "p23_topics": [
                {
                    "topic_id": t["topic_id"],
                    "title": t["title"],
                    "cue_card": t["cue_card"],
                    "part3": t["part3"],
                }
                for t in raw["p2_3"]
            ],
        }
    bank = _load_bank()
    return {
        "p1_topics": [{"topic_id": "fallback-p1", "title": "Part 1", "questions": bank.get("p1", [])}],
        "p23_topics": [
            {"topic_id": f"fallback-{c['id']}", "title": c["text"], "cue_card": c, "part3": []}
            for c in bank.get("p2", [])
        ],
    }


def _tts_url(question_id: str) -> str | None:
    """音频文件存在才给 URL——不存在时诚实返回 null，而非指向 404 的链接。

    存在性检查**每请求实时 stat**（8 题 × 1 次，开销可忽略）：TTS 预生成脚本
    跑完落文件后无需重启进程，tts_url 即刻切换为非 null（review W3 取舍说明）。
    """
    if (TTS_DIR / f"{question_id}.wav").exists():
        return f"{TTS_URL_PREFIX}/{question_id}.wav"
    return None


@router.get("/questions", response_model=list[Question])
async def list_questions(
    part: str | None = Query(default=None, description="题目所属 Part：p1 | p2 | p3"),
) -> list[Question]:
    # 缺参与非法值统一走中文 422（与项目其它端点文案风格一致，review W5）
    if part not in VALID_PARTS:
        raise HTTPException(
            status_code=422, detail=f"part 必须是 {sorted(VALID_PARTS)} 之一"
        )
    items = _load_bank()[part]
    # 每请求随机抽样（见模块 docstring）；题库小于抽样量时全量返回不报错
    sampled = random.sample(items, min(SAMPLE_SIZE[part], len(items)))
    return [
        Question(
            id=item["id"],
            part=item["part"],
            text=item["text"],
            bullets=item.get("bullets"),
            tts_url=_tts_url(item["id"]),
        )
        for item in sampled
    ]
