"""方式 B 会话化接口 + Library 列表（SCHEMA §6.2）。

POST /sessions                    建会话（仅方式 B：mode=ielts + sub_mode=module_pX；
                                  方式 A / 情景对话走 /ws/live 自建）
POST /sessions/{id}/recordings    逐题上传 WAV → 202，后台增量 ingest（转写 + 预上传）
POST /sessions/{id}/review        Get Review：等在途 ingest 排干 → 一次 judge；
                                  立即置 processing，前端跳 /report/{id} 轮询
DELETE /sessions/{id}             Give Up：物理删除会话行（CASCADE）+ 音频文件，不留痕
GET /sessions                     Library 历史会话列表（倒序，含摘要分 + seed 标注）

取代旧一次性 POST /recordings。状态机：recording → processing → completed | failed。
"""

import asyncio
import logging
import re
from contextlib import suppress
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import crud, storage
from app.pipeline import finalize_session, ingest_clip

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])

VALID_B_SUB_MODES = {"module_p1", "module_p2", "module_p3"}

# question_id 白名单：进文件名，掐死路径注入面
_QID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 每会话在途 ingest 任务：review 必须等全部排干再 finalize，否则末题切片
# transcript_json 还是 NULL 会被漏掉（同 live 路径 tee.drain 的语义）。
# 持强引用防 GC 掐任务（Python create_task 陷阱）。
_ingest_tasks: dict[str, set[asyncio.Task]] = {}
_finalize_tasks: set[asyncio.Task] = set()


class CreateSessionRequest(BaseModel):
    mode: str
    sub_mode: str


class SessionCreated(BaseModel):
    session_id: str


class SessionSummary(BaseModel):
    """Library 列表行（SCHEMA §6.2）：会话元数据 + 报告摘要分（未出报告为 null）。"""

    id: str
    mode: str
    sub_mode: str | None
    scenario_case: str | None
    started_at: str
    duration_s: float | None
    status: str
    overall_band: float | None
    wpm: float | None
    is_seed: bool


@router.post("/sessions", response_model=SessionCreated, status_code=201)
async def create_session(body: CreateSessionRequest) -> SessionCreated:
    if body.mode != "ielts":
        raise HTTPException(
            status_code=422,
            detail="POST /sessions 仅用于雅思方式 B；方式 A 与情景对话走 /ws/live",
        )
    if body.sub_mode not in VALID_B_SUB_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"sub_mode 必须是 {sorted(VALID_B_SUB_MODES)} 之一（exam 走 /ws/live）",
        )
    session_id = crud.create_session(
        session_id=uuid4().hex,
        mode="ielts",
        sub_mode=body.sub_mode,
        scenario_case=None,
        audio_path=None,
        duration_s=None,
        status="recording",
    )
    return SessionCreated(session_id=session_id)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions() -> list[SessionSummary]:
    """Library 历史会话列表（倒序）。失败 / 进行中的会话如实列出，前端按 status 展示。"""
    return [SessionSummary(**dict(row)) for row in crud.list_sessions()]


@router.post("/sessions/{session_id}/recordings", status_code=202)
async def upload_recording(
    session_id: str,
    audio: Annotated[UploadFile, File(description="16kHz/16-bit/单声道 PCM WAV")],
    question_id: Annotated[str, Form()],
) -> dict:
    _get_recording_session(session_id)

    if not _QID_RE.match(question_id):
        raise HTTPException(status_code=422, detail="question_id 非法")

    data = await audio.read()
    # read 是让出点：期间 review 可能已翻 processing / Give Up 已删行——必须重校验，
    # 否则本次上传的 ingest 任务会落在 finalize 的排干快照之后被静默漏掉（review C1）。
    # 本检查到 _spawn_ingest 之间全程无 await（同步落盘/记账/建任务），review 端
    # 处理器同样全同步段，单事件循环下两者不可能交错——竞态窗口就此关死。
    _get_recording_session(session_id)
    try:
        duration_s = storage.validate_wav(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    clip_path = storage.save_question_clip(session_id, question_id, data)
    # 时长同步累加：review 入口据此判断「是否已有录音」（在途 ingest 的 turn 行
    # 可能还没建出来，不能拿 turns 表当判据）。同题重录会重复累加——duration_s
    # 仅作 Library 展示/review 判据，报告内 speaking_time 取自合并转写信号，不受影响。
    crud.add_session_duration(session_id, duration_s)
    _spawn_ingest(session_id, clip_path)
    return {"status": "accepted", "question_id": question_id, "duration_s": duration_s}


@router.post("/sessions/{session_id}/review")
async def request_review(session_id: str) -> dict:
    session = _get_recording_session(session_id)
    if not session["duration_s"]:
        raise HTTPException(status_code=422, detail="尚无录音，请先完成至少一题")

    # 立即置 processing（前端马上跳 /report/{id} 轮询，不能见到契约外状态）；
    # finalize 等在途 ingest 排干后在后台跑，自带 completed/failed 状态机。
    crud.update_session_status(session_id, "processing")
    _spawn_finalize(session_id)
    return {"status": "processing"}


@router.delete("/sessions/{session_id}", status_code=204)
async def give_up(session_id: str) -> None:
    if crud.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    # 先删行（CASCADE turns/reports）再删文件；在途 ingest 落空由 _safe_ingest 吞掉
    crud.delete_session(session_id)
    storage.delete_session_audio(session_id)


def _get_recording_session(session_id: str):
    """取会话并校验仍处于 recording 态（404 / 409 中文文案）。"""
    session = crud.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    if session["status"] != "recording":
        raise HTTPException(
            status_code=409,
            detail=f"会话已不在录音中（当前状态 {session['status']}），不能继续操作",
        )
    return session


def _spawn_ingest(session_id: str, clip_path: str) -> None:
    task = asyncio.create_task(asyncio.to_thread(_safe_ingest, session_id, clip_path))
    _ingest_tasks.setdefault(session_id, set()).add(task)

    def _discard(t: asyncio.Task) -> None:
        pending = _ingest_tasks.get(session_id)
        if pending is not None:
            pending.discard(t)
            if not pending:
                _ingest_tasks.pop(session_id, None)

    task.add_done_callback(_discard)


def _safe_ingest(session_id: str, clip_path: str) -> None:
    """单题切片的后台 ingest：异常只记日志（Give Up 后落空属预期，不能炸任务）。"""
    try:
        ingest_clip(session_id, clip_path)
    except Exception:
        logger.exception("方式 B 切片 ingest 失败: session=%s clip=%s", session_id, clip_path)


def _spawn_finalize(session_id: str) -> None:
    task = asyncio.create_task(_drain_and_finalize(session_id))
    _finalize_tasks.add(task)
    task.add_done_callback(_finalize_tasks.discard)


async def _drain_and_finalize(session_id: str) -> None:
    # 等本会话全部在途 ingest 落库（转写/预上传挂 turns 行）再 finalize
    pending = list(_ingest_tasks.get(session_id, ()))
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.to_thread(_run_finalize, session_id)


def _run_finalize(session_id: str) -> None:
    # finalize_session 失败时已在自身 except 里置 status=failed 并记日志；这里的
    # suppress 只是防后台 task 留未取异常，不会丢失任何状态/日志副作用。
    # 方式 B 无 Live、无 FC 应答台：finalize 的 live_feedback 走默认 None
    # （live 路径的同名包装在 live_ws.py，签名多一个 live_feedback——勿混淆）。
    with suppress(Exception):
        finalize_session(session_id)
