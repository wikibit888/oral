"""报告查询入口：处理页轮询状态、报告页取完整结果、失败重跑恢复。

GET  /reports/{id}        返回会话状态；status=completed 时附完整报告 JSON（SCHEMA §5.2）。
POST /reports/{id}/retry  失败 / 卡死会话的恢复路径：从已落库的转写切片重跑一次 judge。
课后流水线在后台异步跑，前端据 status 决定继续轮询还是渲染报告。
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app import crud
from app.pipeline import finalize_session
from app.report import Report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])

# 可直接重跑的状态：failed（系统错误终态）/ processing（可能卡死）。completed 仅在
# 报告体缺失/损坏时才可重跑（见 _is_recoverable）；live/recording 仍在进行中，不重跑。
_RETRYABLE_STATUSES = {"failed", "processing"}

# 后台重跑 task 持强引用防 GC（同 sessions.py 的 _finalize_tasks 模式）。
_retry_tasks: set[asyncio.Task] = set()
# 在途重跑的 session 去重：防前端 stalled 误判 / 连点 Retry 触发同一 session 并发
# double-finalize（双倍 judge 配额；temp=0 也不保证两次产出逐字一致）。
_retry_inflight: set[str] = set()


class ReportResponse(BaseModel):
    id: str
    mode: str
    # SCHEMA §5.1 枚举: live | recording | processing | completed | failed
    status: str
    report: Report | None = None     # 仅 status=completed 且报告已落库时有值


@router.get("/reports/{session_id}", response_model=ReportResponse)
async def get_report(session_id: str) -> ReportResponse:
    session = crud.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")

    return ReportResponse(
        id=session_id,
        mode=session["mode"],
        status=session["status"],
        report=_load_report(session_id) if session["status"] == "completed" else None,
    )


def _load_report(session_id: str) -> Report | None:
    """取并校验已落库报告体；缺失 / 损坏（跨版本 schema 漂移）→ None（不让 GET 500）。"""
    row = crud.get_report(session_id)
    if row is None:
        return None
    try:
        return Report.model_validate_json(row["report_json"])
    except ValidationError:
        logger.exception("report_json 解析失败，降级 report=None: session=%s", session_id)
        return None


def _is_recoverable(status: str, session_id: str) -> bool:
    """会话是否可重跑恢复。

    failed / processing：可（系统错误终态 / 可能卡死）。
    completed：仅当报告体缺失或损坏才可——绝不重跑一份已正常落库的报告（避免无谓的
    judge 调用、避免覆盖好报告）；这是 GET 降级 report=None 的死骨架的唯一出路。
    live / recording：仍在进行中，不可。
    """
    if status in _RETRYABLE_STATUSES:
        return True
    if status == "completed":
        return _load_report(session_id) is None
    return False


@router.post("/reports/{session_id}/retry")
async def retry_report(session_id: str) -> dict:
    """失败 / 卡死 / 报告损坏会话的恢复路径：从已落库的转写切片重跑一次 judge（前端 Retry 调它）。

    转写切片（turns.transcript_json）在会话内就已落库，重跑只需再调一次 judge——
    覆盖 live / 方式 B / 情景所有入口。情景的会话内 FC 实录（language_help /
    grammar_note）是内存态、重跑取不到，故恢复出的情景报告无 live_feedback 段
    （可接受的降级——总好过永久 failed）。
    同一 session 已有在途重跑则不再并发起第二个（去重防 double-finalize）。
    """
    session = crud.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    if not _is_recoverable(session["status"], session_id):
        raise HTTPException(
            status_code=409,
            detail=f"会话当前状态 {session['status']} 不可重跑（仅失败 / 处理中 / 报告损坏可恢复）",
        )

    # 已有在途重跑：直接复用，不并发第二个（前端 stalled 误判 / 连点都安全幂等）。
    if session_id in _retry_inflight:
        return {"status": "processing"}

    # 立即置 processing（前端继续轮询），finalize 在后台跑、自带 completed/failed 状态机。
    crud.update_session_status(session_id, "processing")
    _retry_inflight.add(session_id)
    task = asyncio.create_task(asyncio.to_thread(_run_finalize, session_id))
    _retry_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _retry_tasks.discard(t)
        _retry_inflight.discard(session_id)

    task.add_done_callback(_done)
    return {"status": "processing"}


def _run_finalize(session_id: str) -> None:
    # finalize_session 自带 failed 状态机 + 异常日志并 re-raise；这里兜底记一行，
    # 防止它在置 failed 之前就异常（如 DB 锁）时悄无声息（review W3）。
    try:
        finalize_session(session_id)
    except Exception:
        logger.exception("重跑 finalize 失败: session=%s", session_id)
