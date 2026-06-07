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
import time
from contextlib import suppress
from typing import Any, Coroutine
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import random

from app import crud
from app.api.questions import _load_bank
from app.live.bridge import bridge
from app.live.client import connect_live
from app.live.director import (
    EXAMINER_SYSTEM_INSTRUCTION,
    IeltsDirector,
    send_stage_direction,
)
from app.live.help import LanguageHelpDesk, ScenarioNudger
from app.live.tee import UserAudioTee
from app.pipeline import finalize_session
from app.scenario_cases import CASES as SCENARIO_CASES, language_help_tool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

VALID_TURN_MODES = {"ptt", "natural"}
# case 白名单由注册表推导：加 case 只改 scenario_cases.py（SCENARIO.md §2）
VALID_SCENARIO_CASES = frozenset(SCENARIO_CASES)

# fire-and-forget 的后台任务（finalize / 孤儿清理）持强引用：事件循环只持
# 弱引用，不留住会被 GC 中途掐掉（Python 文档明示的 create_task 陷阱）。
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _parse_params(websocket: WebSocket) -> tuple[str, str | None, str | None, str]:
    """解析并校验连接参数，返回 (mode, sub_mode, scenario_case, turn)。

    WS 侧 mode=ielts_a 映射存储层 mode='ielts' + sub_mode='exam'（方式 A 即
    整场模拟考）；scenario 必带 case。turn=ptt|natural（默认 natural）连接时
    确定、会话中切换走重连：natural 走 Live 内建 VAD，ptt 关 VAD、由显式
    turn_end 控制断轮次（bridge 接线）。非法参数抛 ValueError（中文文案直接
    回给前端展示）。
    """
    params = websocket.query_params
    turn = params.get("turn", "natural")
    if turn not in VALID_TURN_MODES:
        raise ValueError(f"turn 必须是 {sorted(VALID_TURN_MODES)} 之一")
    mode = params.get("mode")
    if mode == "ielts_a":
        return "ielts", "exam", None, turn
    if mode == "scenario":
        case = params.get("case")
        if case not in VALID_SCENARIO_CASES:
            raise ValueError(f"scenario 模式需 case ∈ {sorted(VALID_SCENARIO_CASES)}")
        return "scenario", None, case, turn
    raise ValueError("mode 必须是 ['ielts_a', 'scenario'] 之一")


@router.websocket("/ws/live")
async def live_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        mode, sub_mode, scenario_case, turn_mode = _parse_params(websocket)
    except ValueError as e:
        # 参数错属客户端 bug：回可读 error 后关闭，不碰 Live、不落会话行
        with suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
        return

    session_id: str | None = None
    tee: UserAudioTee | None = None
    director: IeltsDirector | None = None
    ended = False
    # 方式 A：中立考官 persona + 导演状态机（cue card 随机抽自题库 p2），
    # 无 tools 保持中立；情景：按 case 注入角色 persona + language_help tool
    # （声明按 case 生成——场景标签锚定模型选词；_parse_params 已保证 case 在注册表内）
    tools = None
    if sub_mode == "exam":
        system_instruction = EXAMINER_SYSTEM_INSTRUCTION
    elif mode == "scenario":
        system_instruction = SCENARIO_CASES[scenario_case].persona
        tools = [language_help_tool(scenario_case)]
    else:
        system_instruction = None
    try:
        async with connect_live(turn_mode, system_instruction, tools) as live_session:
            # Live 建链成功才落会话行（连不上不留孤儿行）。客户端中途断开的
            # 会话不触发 judge（契约：仅 end_session 触发）：说过话的停在
            # recording 态留素材，零切片的在 finally 里清掉。
            session_id = crud.create_session(
                session_id=uuid4().hex,
                mode=mode,
                sub_mode=sub_mode,
                scenario_case=scenario_case,
                audio_path=None,
                duration_s=None,
                status="live",   # SCHEMA §5.1：Live 会话中（recording 留给方式 B 录音）
            )
            await websocket.send_json(
                {"type": "session_started", "session_id": session_id}
            )
            # 会话时长起点（单调钟，免疫系统时间跳变）：live 行建行时
            # duration_s=NULL 且方式 B 的逐题累加链路不经过这里，无人回填
            # 会让 Library 时长列恒 '—'（done/007 反馈①）。
            session_start = time.monotonic()
            # tee 把上行用户音频按轮次边界切片喂增量流水线（whisper + 预上传
            # 在会话内后台跑完）。end_session → 封尾切片 + 自动触发课后 judge
            # （SCHEMA §6.1）。回调在消费到 end_session 的瞬间调度成独立 task：
            # 前端发完可能立即断开并跳 /report/{session_id} 轮询，本协程随时
            # 被取消，不能事后再触发。
            tee = UserAudioTee(session_id)

            def _on_end_session() -> None:
                nonlocal ended
                ended = True
                # 墙钟时长回填：end_session 是 live 会话唯一收束语义，bridge
                # 消费后即 return——只触发一次，不会重复累加。弃局（断开不 End）
                # 不回填，duration 留 NULL 如实表示未走完。
                crud.add_session_duration(session_id, time.monotonic() - session_start)
                # 立即翻转 processing：drain/ingest 在途窗口里前端已开始轮询，
                # 不能让它看到契约外的过渡态卡住（联调发现①）
                crud.update_session_status(session_id, "processing")
                tee.finish()
                _schedule_finalize(tee, session_id)

            tool_handler = None
            nudger = None
            if sub_mode == "exam":
                director = IeltsDirector(_pick_cue_card())
                await director.start(websocket, live_session)
            elif mode == "scenario":
                # 情景也由 AI 先开口（done/006 实录用户面对冷场先说话）：
                # 随机抽一条开场舞台指令，角色入戏开场并以一个引导性问题
                # 把用户带进场景。对评测零污染——文本回合不进 tee/转写样本。
                await send_stage_direction(live_session, _pick_opener(scenario_case))
                # language_help 应答台：模板控形 + 控频 + teaching 事件直发前端
                # （case 感知：{scene} 槽 + 事件 case 字段）
                tool_handler = LanguageHelpDesk(websocket, scenario_case)
                # 沉默分级探询执行端：前端计时器发 nudge {stage}，查表注入
                # 舞台指令（方式 A 不接——考官中立不探询）
                nudger = ScenarioNudger(scenario_case)

            await bridge(
                websocket,
                live_session,
                turn_mode=turn_mode,
                tee=tee,
                on_end_session=_on_end_session,
                director=director,
                tool_handler=tool_handler,
                nudger=nudger,
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
        # 导演备题计时器是孤儿任务源：会话怎么结束都要取消（同步调用，无 await 点）
        if director is not None:
            director.cancel_timers()
        # 弃局且一个切片都没切出（React StrictMode 双连接的首条、误点进入等）
        # → 删孤儿行（联调发现③）。零切片 = 从未发起 ingest，删行无竞态。
        # 放在 close 之前：本协程可能已被取消，close 的 await 点会再抛
        # CancelledError 中断 finally，先把清理任务同步调度出去。
        if session_id is not None and not ended and (tee is None or tee.clip_count == 0):
            _schedule_orphan_cleanup(session_id)
        with suppress(Exception):
            await websocket.close()


def _pick_cue_card() -> dict:
    """从题库 p2 随机抽一张 cue card（静态精选库 8 张，IELTS.md §2）。"""
    return random.choice(_load_bank()["p2"])


def _pick_opener(case: str) -> str:
    """从 case 注册表随机抽一条开场舞台指令（多次练习不重样，同 cue card 模式）。"""
    return random.choice(SCENARIO_CASES[case].openers)


def _schedule_finalize(tee: UserAudioTee, session_id: str) -> None:
    """调度课后收口为独立 task：先排干切片 ingest，再跑一次 judge。"""
    _spawn_background(_drain_and_finalize(tee, session_id))


async def _drain_and_finalize(tee: UserAudioTee, session_id: str) -> None:
    # 必须先等全部切片转写/预上传落库再 finalize——否则在途的末轮切片
    # transcript_json 还是 NULL，会被 list_processed_user_turns 漏掉。
    await tee.drain()
    await asyncio.to_thread(_run_finalize, session_id)


def _run_finalize(session_id: str) -> None:
    # finalize_session 自带 failed 状态机 + 异常日志；这里吞掉防 task 留未取异常
    with suppress(Exception):
        finalize_session(session_id)


def _schedule_orphan_cleanup(session_id: str) -> None:
    """后台删除零切片弃局的孤儿会话行。"""
    _spawn_background(asyncio.to_thread(_cleanup_orphan, session_id))


def _cleanup_orphan(session_id: str) -> None:
    try:
        session = crud.get_session(session_id)
        # 再核一遍状态：只删仍停在 live 的行，绝不误删已进评测的会话
        if session is not None and session["status"] == "live":
            crud.delete_session(session_id)
    except Exception:
        logger.exception("孤儿会话清理失败: session=%s", session_id)
