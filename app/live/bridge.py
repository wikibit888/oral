"""WS ⇄ Gemini Live 双向桥接（纯逻辑，websocket / session 都按鸭子类型注入，可单测）。

帧契约（FRONTEND §5 事件契约的桥接子集；建链 session_started 由入口层发）：
- 浏览器 → 后端：binary = 16k PCM16 音频帧；text = JSON 控制消息
  {"type": "end_session"} / {"type": "turn_end"}（仅 PTT 模式有效）。
- 后端 → 浏览器：binary = 24k PCM16 音频帧；text = JSON 事件
  transcript_delta {role: user|examiner, text} / interrupted（barge-in，
  前端立即清空 24k 播放队列）/ turn_complete（考官回合结束）/
  latency_ms {value}（考官首帧时的响应延迟，app/live/latency.py）。

轮次边界按连接时确定的 turn 模式（SCHEMA §6.1）：
- natural：Live 内建 VAD 自动断轮次；turn_end 控制记日志忽略。
- ptt：内建 VAD 已关（client._live_config）——上行首帧自动补 activity_start，
  turn_end 控制发 activity_end（前端按住说话、松开发 turn_end）。
任一方向结束（客户端断开 / end_session / Live 流结束）即整体收束。
"""

import asyncio
import json
import logging

from google.genai import types

from app.live.client import AUDIO_MIME
from app.live.latency import LatencyMeter

logger = logging.getLogger(__name__)


async def bridge(
    websocket, session, *, turn_mode="natural", tee=None, on_end_session=None,
    director=None,
) -> None:
    """并发跑上行 / 下行两个泵，任一结束就取消另一个；泵内异常向上抛。

    turn_mode：natural | ptt（连接时确定，决定上行泵的轮次信号语义）。
    tee：用户音频分叉器（app/live/tee.py，鸭子类型）。泵内在对应位置同步调
    钩子：上行帧 on_user_frame、下行音频 on_model_audio、事件 on_interrupted /
    on_turn_complete——切片的轮次边界与发给前端的事件天然同一来源。
    director：方式 A 导演状态机（app/live/director.py，鸭子类型）。上行泵按
    `input_paused` 丢备题期音频帧（不进 Live、不进 tee）、`ready` 控制转给
    `on_ready`；下行泵在 turn_complete 事件发出后 await `on_turn_complete`
    推进状态机（导演提示 / part_change 等事件由其内部发出）。
    on_end_session：消费到 end_session 的瞬间在上行泵内同步回调（无 await 点），
    是「会话正常收束」的唯一信号（客户端断开 / Live 流自行结束都不会触发）。
    调用方用它收尾 tee 并调度课后 judge——前端发完 end_session 可能立即断开并
    跳报告页，本协程随时会被取消，收束后的代码不保证执行，故不能放在 bridge 之后。
    """
    # 延迟徽章（latency_ms 事件）：两泵共享一个测量器——上行采用户停说点，
    # 下行在考官首帧出数（FRONTEND §5）
    meter = LatencyMeter(turn_mode)
    up = asyncio.create_task(
        _pump_upstream(websocket, session, turn_mode, tee, on_end_session, meter, director)
    )
    down = asyncio.create_task(_pump_downstream(websocket, session, tee, meter, director))
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


async def _pump_upstream(
    websocket, session, turn_mode="natural", tee=None, on_end_session=None, meter=None,
    director=None,
) -> None:
    """浏览器 → Live：二进制音频帧转发（tee / meter 同步分叉）；文本按控制消息处理。

    ptt 模式：首帧音频前补 activity_start，turn_end 控制发 activity_end——
    内建 VAD 已关，没有这对信号 Live 不会响应。
    director 备题期（input_paused）丢弃音频帧：不进 Live、不进 tee、不进 meter——
    备题嘀咕不是说话样本（IELTS.md §2 P2 准备阶段 Live 输入暂停）。
    收到 end_session 先回调 on_end_session 再返回；客户端断开直接返回。
    """
    ptt = turn_mode == "ptt"
    activity_open = False
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if (data := message.get("bytes")) is not None:
            if director is not None and director.input_paused:
                continue                    # 备题期整帧丢弃
            if tee is not None:
                tee.on_user_frame(data)
            if meter is not None:
                meter.on_user_frame(data)   # natural：非静音帧刷新停说时刻
            if ptt and not activity_open:
                await session.send_realtime_input(activity_start=types.ActivityStart())
                activity_open = True
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type=AUDIO_MIME)
            )
        elif (text := message.get("text")) is not None:
            control = _parse_control(text)
            if control == "end_session":
                if on_end_session is not None:
                    on_end_session()
                return
            if control == "ready":
                if director is not None:
                    await director.on_ready(websocket, session)   # 提前结束备题
                else:
                    logger.debug("ready 被忽略：无 director（非方式 A）")
                continue
            if control == "turn_end":
                if ptt and activity_open:
                    if meter is not None:
                        meter.on_turn_end()  # ptt：松开即停说时刻
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                    activity_open = False
                else:
                    # natural 模式（VAD 自动断轮）或按下前误发：忽略。
                    # debug 级——前端 bug 反复误发时不至于刷屏（review 建议）
                    logger.debug(
                        "turn_end 被忽略：turn_mode=%s activity_open=%s",
                        turn_mode, activity_open,
                    )


def _parse_control(text: str) -> str | None:
    """解析控制消息，返回类型字符串；未知/非法消息记日志忽略（None），不断流。"""
    try:
        control = json.loads(text)
    except ValueError:
        logger.warning("live WS 收到非 JSON 文本消息，忽略：%.100s", text)
        return None
    kind = control.get("type")
    if kind in ("end_session", "turn_end", "ready"):
        return kind
    logger.warning("live WS 收到未知控制消息，忽略：%.100s", text)
    return None


async def _pump_downstream(websocket, session, tee=None, meter=None, director=None) -> None:
    """Live → 浏览器：音频字节直发 binary；双向转写发 transcript_delta 事件。

    session.receive() 的迭代器在一轮结束后耗尽，外层 while True 续接下一轮
    （与 gemini_live.py demo 同模式）。
    """
    # tee / meter 钩子一律在 await 发送之前调：钩子只动内存、无 await 点，保证
    # 切片边界状态先于事件落定——若放在 send 之后，send 让出控制权的窗口里
    # 上行泵可能已处理新帧，边界就漂了。
    while True:
        async for response in session.receive():
            if response.data:
                if tee is not None:
                    tee.on_model_audio()    # 考官开口 = 用户切片的轮次边界
                if director is not None:
                    director.on_model_audio()   # 标记本轮考官真发声（空轮不推进 FSM）
                latency_ms = meter.on_model_audio() if meter is not None else None
                await websocket.send_bytes(response.data)
                if latency_ms is not None:  # 考官首帧才有值（一轮一次）
                    await websocket.send_json(
                        {"type": "latency_ms", "value": latency_ms}
                    )
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
                # 方式 A 导演：考官转写喂状态机做转场短语检测（模型驱动转场的主推力，
                # app/live/director.py）。同步钩子、无 await——只累积 + 种 _pending，
                # 真正转场延迟到 turn_complete。放在 send 之前：边界状态先于事件落定。
                if director is not None:
                    director.on_examiner_transcript(ot.text)
                await websocket.send_json(
                    {"type": "transcript_delta", "role": "examiner", "text": ot.text}
                )
            # barge-in：用户插话时 Live 置 interrupted，前端收到后立即清空 24k
            # 播放队列（FRONTEND §5）。放在音频之后发：同一响应里残留的旧回合
            # 音频字节先入队、随即被这条事件整体清掉，不会漏。
            if sc.interrupted:
                if tee is not None:
                    tee.on_interrupted()    # 地板归还用户 + 预缓冲回补打断起头
                if director is not None:
                    director.on_interrupted()   # 清发声标记，防残留误计空轮（review C1）
                if meter is not None:
                    meter.on_turn_taken_back()
                await websocket.send_json({"type": "interrupted"})
            # 考官回合结束（VAD/turn 边界）；PTT 模式前端也靠它解锁下一次按键
            if sc.turn_complete:
                if tee is not None:
                    tee.on_turn_complete()  # 地板归还用户，开新切片
                if meter is not None:
                    meter.on_turn_taken_back()
                await websocket.send_json({"type": "turn_complete"})
                # 方式 A 导演：考官轮结束 = 状态机唯一推进时钟（导演提示 /
                # part_change 等由其内部发出）。放在事件之后：前端先看到
                # turn_complete 再看到可能的 part_change，时序直观。
                if director is not None:
                    await director.on_turn_complete(websocket, session)
