"""方式 B 题库入口：GET /questions?part=p1|p2|p3（SCHEMA §6.5 / IELTS.md §3）。

题目来自静态库 `data/questions.json`（p2 同时充当方式 A 的 cue card 库），
进程内缓存一次；`tts_url` 按预生成音频文件（data/tts/{id}.wav，TTS 项产出）
的存在性回填——音频未生成时为 null，前端降级为纯文字读题。
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["questions"])

VALID_PARTS = {"p1", "p2", "p3"}

# 路径用模块常量（非 settings）：静态资源位置是仓库布局的一部分，不随环境变化。
# 以本文件位置锚定仓库根（app/api/ 上两级），不依赖进程 cwd（review W1）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = _REPO_ROOT / "data" / "questions.json"
TTS_DIR = _REPO_ROOT / "data" / "tts"
TTS_URL_PREFIX = "/static/tts"


class Question(BaseModel):
    id: str
    part: str                       # p1 | p2 | p3
    text: str
    bullets: list[str] | None = None   # 仅 p2 cue card（4 条）
    tts_url: str | None = None      # 预生成 TTS；未生成为 null（前端纯文字降级）


@lru_cache(maxsize=1)
def _load_bank() -> dict[str, list[dict]]:
    """读静态题库并按 part 分组缓存（demo 静态数据，进程生命周期内不变）。

    part 字段在加载时注入每个条目（数据文件按组组织、条目内不重复存 part），
    下游不再依赖调用方传入（review S2）。
    """
    raw = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    bank: dict[str, list[dict]] = {}
    for part in VALID_PARTS:
        bank[part] = [{**item, "part": part} for item in raw.get(part, [])]
    return bank


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
    return [
        Question(
            id=item["id"],
            part=item["part"],
            text=item["text"],
            bullets=item.get("bullets"),
            tts_url=_tts_url(item["id"]),
        )
        for item in _load_bank()[part]
    ]
