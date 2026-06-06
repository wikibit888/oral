"""实时对话 WS 入口：浏览器 ⇄ 本代理 ⇄ Gemini Live（雅思方式 A + 情景对话）。

连接参数（FRONTEND §5 / SCHEMA §6.1）：
    /ws/live?mode=ielts_a|scenario&case=ordering|meeting&turn=ptt|natural
建链即落 sessions 行并回发 session_started {session_id}（前端报告跳转用）；
收到 end_session 控制消息后收束会话并自动触发课后 judge（finalize_session，
转写/信号由增量流水线在会话内就绪——音频 tee 项接线后生效）。

每个 WS 连接对应一条独立 Live 会话。我们自己包代理（而非前端直连 Live），
是为了后续 PR 能在上行路径上 tee 用户音频 + 帧时间戳，供课后切片进 P1 流水线。
帧契约见 app/live/bridge.py。
"""

import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import crud
from app.live.bridge import bridge
from app.live.client import connect_live
from app.live.tee import UserAudioTee
from app.pipeline import finalize_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

VALID_TURN_MODES = {"ptt", "natural"}
VALID_SCENARIO_CASES = {"ordering", "meeting"}

# fire-and-forget 的 finalize 任务持强引用：事件循环只持弱引用，
# 不留住会被 GC 中途掐掉（Python 文档明示的 create_task 陷阱）。
_finalize_tasks: set[asyncio.Task] = set()


def _parse_params(websocket: WebSocket) -> tuple[str, str | None, str | None]:
    """解析并校验连接参数，返回 sessions 行的 (mode, sub_mode, scenario_case)。

    WS 侧 mode=ielts_a 映射存储层 mode='ielts' + sub_mode='exam'（方式 A 即
    整场模拟考）；scenario 必带 case。turn=ptt|natural 仅校验（默认 natural，
    连接时确定、会话中切换走重连）——PTT 的显式 turn_end 语义由后续
    「PTT + 轮次结束」项接线，当前两种取值行为一致（Live 内建 VAD 断轮次）。
    非法参数抛 ValueError（中文文案直接回给前端展示）。
    """
    params = websocket.query_params
    turn = params.get("turn", "natural")
    if turn not in VALID_TURN_MODES:
        raise ValueError(f"turn 必须是 {sorted(VALID_TURN_MODES)} 之一")
    mode = params.get("mode")
    if mode == "ielts_a":
        return "ielts", "exam", None
    if mode == "scenario":
        case = params.get("case")
        if case not in VALID_SCENARIO_CASES:
            raise ValueError(f"scenario 模式需 case ∈ {sorted(VALID_SCENARIO_CASES)}")
        return "scenario", None, case
    raise ValueError("mode 必须是 ['ielts_a', 'scenario'] 之一")


@router.websocket("/ws/live")
async def live_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        mode, sub_mode, scenario_case = _parse_params(websocket)
    except ValueError as e:
        # 参数错属客户端 bug：回可读 error 后关闭，不碰 Live、不落会话行
        with suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
        return

    try:
        async with connect_live() as live_session:
            # Live 建链成功才落会话行（连不上不留孤儿行）。客户端中途断开的
            # 会话停在 recording 态，不触发 judge（契约：仅 end_session 触发）。
            session_id = crud.create_session(
                session_id=uuid4().hex,
                mode=mode,
                sub_mode=sub_mode,
                scenario_case=scenario_case,
                audio_path=None,
                duration_s=None,
                status="recording",
            )
            await websocket.send_json(
                {"type": "session_started", "session_id": session_id}
            )
            # tee 把上行用户音频按轮次边界切片喂增量流水线（whisper + 预上传
            # 在会话内后台跑完）。end_session → 封尾切片 + 自动触发课后 judge
            # （SCHEMA §6.1）。回调在消费到 end_session 的瞬间调度成独立 task：
            # 前端发完可能立即断开并跳 /report/{session_id} 轮询，本协程随时
            # 被取消，不能事后再触发。
            tee = UserAudioTee(session_id)

            def _on_end_session() -> None:
                tee.finish()
                _schedule_finalize(tee, session_id)

            await bridge(
                websocket,
                live_session,
                tee=tee,
                on_end_session=_on_end_session,
            )
    except WebSocketDisconnect:
        pass  # 客户端正常断开
    except Exception:
        logger.exception("live WS 会话异常")
        # 尽力告知前端再关闭；连接可能已死，失败就算了
        with suppress(Exception):
            await websocket.send_json(
                {"type": "error", "message": "实时会话异常，请重试。"}
            )
    finally:
        with suppress(Exception):
            await websocket.close()


def _schedule_finalize(tee: UserAudioTee, session_id: str) -> None:
    """调度课后收口为独立 task：先排干切片 ingest，再跑一次 judge。"""
    task = asyncio.create_task(_drain_and_finalize(tee, session_id))
    _finalize_tasks.add(task)
    task.add_done_callback(_finalize_tasks.discard)


async def _drain_and_finalize(tee: UserAudioTee, session_id: str) -> None:
    # 必须先等全部切片转写/预上传落库再 finalize——否则在途的末轮切片
    # transcript_json 还是 NULL，会被 list_processed_user_turns 漏掉。
    await tee.drain()
    await asyncio.to_thread(_run_finalize, session_id)


def _run_finalize(session_id: str) -> None:
    # finalize_session 自带 failed 状态机 + 异常日志；这里吞掉防 task 留未取异常
    with suppress(Exception):
        finalize_session(session_id)
