"""WS ⇄ Gemini Live 双向桥接（纯逻辑，websocket / session 都按鸭子类型注入，可单测）。

帧契约（FRONTEND §5 事件契约的桥接子集；建链 session_started 由入口层发）：
- 浏览器 → 后端：binary = 16k PCM16 音频帧；text = JSON 控制消息
  （目前支持 {"type": "end_session"}；PTT/turn_end 等后续 PR 加）。
- 后端 → 浏览器：binary = 24k PCM16 音频帧；text = JSON 事件
  transcript_delta {role: user|examiner, text} / interrupted（barge-in，
  前端立即清空 24k 播放队列）/ turn_complete（考官回合结束）。

上行靠 Live 内建 VAD 自动断轮次（PTT 显式 turn_end 在后续 PR 叠加）。
任一方向结束（客户端断开 / end_session / Live 流结束）即整体收束。
"""

import asyncio
import json
import logging

from google.genai import types

from app.live.client import AUDIO_MIME

logger = logging.getLogger(__name__)


async def bridge(websocket, session, *, tee=None, on_end_session=None) -> None:
    """并发跑上行 / 下行两个泵，任一结束就取消另一个；泵内异常向上抛。

    tee：用户音频分叉器（app/live/tee.py，鸭子类型）。泵内在对应位置同步调
    钩子：上行帧 on_user_frame、下行音频 on_model_audio、事件 on_interrupted /
    on_turn_complete——切片的轮次边界与发给前端的事件天然同一来源。
    on_end_session：消费到 end_session 的瞬间在上行泵内同步回调（无 await 点），
    是「会话正常收束」的唯一信号（客户端断开 / Live 流自行结束都不会触发）。
    调用方用它收尾 tee 并调度课后 judge——前端发完 end_session 可能立即断开并
    跳报告页，本协程随时会被取消，收束后的代码不保证执行，故不能放在 bridge 之后。
    """
    up = asyncio.create_task(_pump_upstream(websocket, session, tee, on_end_session))
    down = asyncio.create_task(_pump_downstream(websocket, session, tee))
    try:
        done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # finally 兜底取消两端：覆盖 bridge 自身被外部取消的情形（如 uvicorn 优雅停机
        # 取消端点协程时，asyncio.wait 不会替我们取消子任务），不泄漏任务。
        up.cancel()
        down.cancel()
        await asyncio.gather(up, down, return_exceptions=True)
    for task in done:
        if (exc := task.exception()) is not None:
            raise exc


async def _pump_upstream(websocket, session, tee=None, on_end_session=None) -> None:
    """浏览器 → Live：二进制音频帧转发（tee 同步分叉）；文本按控制消息处理。

    收到 end_session 先回调 on_end_session 再返回；客户端断开直接返回。
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if (data := message.get("bytes")) is not None:
            if tee is not None:
                tee.on_user_frame(data)
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type=AUDIO_MIME)
            )
        elif (text := message.get("text")) is not None:
            if _handle_control(text):
                if on_end_session is not None:
                    on_end_session()
                return


def _handle_control(text: str) -> bool:
    """处理控制消息；返回 True 表示会话应结束。未知/非法消息记日志忽略，不断流。"""
    try:
        control = json.loads(text)
    except ValueError:
        logger.warning("live WS 收到非 JSON 文本消息，忽略：%.100s", text)
        return False
    if control.get("type") == "end_session":
        return True
    logger.warning("live WS 收到未知控制消息，忽略：%.100s", text)
    return False


async def _pump_downstream(websocket, session, tee=None) -> None:
    """Live → 浏览器：音频字节直发 binary；双向转写发 transcript_delta 事件。

    session.receive() 的迭代器在一轮结束后耗尽，外层 while True 续接下一轮
    （与 gemini_live.py demo 同模式）。
    """
    # tee 钩子一律在 await 发送之前调：钩子只动内存、无 await 点，保证切片
    # 边界状态先于事件落定——若放在 send 之后，send 让出控制权的窗口里上行泵
    # 可能已处理新帧，边界就漂了。
    while True:
        async for response in session.receive():
            if response.data:
                if tee is not None:
                    tee.on_model_audio()    # 考官开口 = 用户切片的轮次边界
                await websocket.send_bytes(response.data)
            sc = response.server_content
            if sc is None:
                continue
            it = sc.input_transcription
            if it is not None and it.text:
                await websocket.send_json(
                    {"type": "transcript_delta", "role": "user", "text": it.text}
                )
            ot = sc.output_transcription
            if ot is not None and ot.text:
                await websocket.send_json(
                    {"type": "transcript_delta", "role": "examiner", "text": ot.text}
                )
            # barge-in：用户插话时 Live 置 interrupted，前端收到后立即清空 24k
            # 播放队列（FRONTEND §5）。放在音频之后发：同一响应里残留的旧回合
            # 音频字节先入队、随即被这条事件整体清掉，不会漏。
            if sc.interrupted:
                if tee is not None:
                    tee.on_interrupted()    # 地板归还用户 + 预缓冲回补打断起头
                await websocket.send_json({"type": "interrupted"})
            # 考官回合结束（VAD/turn 边界）；PTT 模式前端也靠它解锁下一次按键
            if sc.turn_complete:
                if tee is not None:
                    tee.on_turn_complete()  # 地板归还用户，开新切片
                await websocket.send_json({"type": "turn_complete"})
