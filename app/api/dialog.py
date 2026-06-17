"""人机对话回看：整场有序对话流 + 逐轮音频取流（dialog 卡片 / Dialog 视图）。

GET /sessions/{id}/dialog              整场对话流（user/assistant 按时序，每轮含 audio_url）
GET /sessions/{id}/turns/{tid}/audio   单回合音频文件（WAV，FileResponse）

音频走「按 turn 取流的 FileResponse」而非 StaticFiles 目录挂载：可校验回合归属、
挡路径注入、不暴露可枚举的全量录音目录（与 Give Up「不留痕」语义一致）。
仅 live 路径（雅思方式 A + 情景）会产出 assistant 回合；方式 B 不在 dialog 卡片范围内。
"""

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import crud
from app.config import settings

router = APIRouter(tags=["dialog"])


class DialogTurn(BaseModel):
    """一条对话回合（前端按 role 分左右：user=右/你，其余=左/AI，标签由 mode/case 决定）。"""

    turn_id: int
    role: str                    # user | assistant
    text: str | None             # 转写文本（user 由 whisper、assistant 由 Live 输出转写）
    start_ts: float | None       # 相对会话起点秒（排序/对齐用）
    end_ts: float | None
    audio_url: str | None        # 有切片才有；点击回放该回合录音


class DialogResponse(BaseModel):
    """整场对话流 + 会话元数据（mode/case 供前端推 AI 侧英文角色标签：
    雅思=Examiner、点餐=Server、会议=Colleague）。"""

    mode: str                    # ielts | scenario
    scenario_case: str | None    # ordering | meeting（仅情景）
    turns: list[DialogTurn]


@router.get("/sessions/{session_id}/dialog", response_model=DialogResponse)
async def get_dialog(session_id: str) -> DialogResponse:
    """整场人机对话流（时序）+ 会话元数据。会话不存在 → 404；无回合 → 空 turns。"""
    session = crud.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    return DialogResponse(
        mode=session["mode"],
        scenario_case=session["scenario_case"],
        turns=[_to_turn(session_id, row) for row in crud.list_dialog_turns(session_id)],
    )


def _to_turn(session_id: str, row: sqlite3.Row) -> DialogTurn:
    return DialogTurn(
        turn_id=row["id"],
        role=row["role"],
        text=row["text"],
        start_ts=row["start_ts"],
        end_ts=row["end_ts"],
        audio_url=(
            f"/sessions/{session_id}/turns/{row['id']}/audio"
            if row["clip_path"]
            else None
        ),
    )


@router.get("/sessions/{session_id}/turns/{turn_id}/audio")
async def get_turn_audio(session_id: str, turn_id: int) -> FileResponse:
    """取某回合的音频文件回放。回合不属于该会话 / 无切片 / 文件缺失 → 404。"""
    turn = crud.get_turn(turn_id)
    if turn is None or turn["session_id"] != session_id or not turn["clip_path"]:
        raise HTTPException(status_code=404, detail="该回合无音频")
    path = Path(turn["clip_path"]).resolve()
    audio_root = Path(settings.audio_dir).resolve()
    # 路径注入防御：clip_path 必须落在 audio_dir 内，且文件确实存在
    if audio_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    return FileResponse(path, media_type="audio/wav")
