"""方式 A 导演状态机单测（模型驱动 + 短语检测 + 延迟 UI + 安全网）。

ws / session 皆假体，零网络；async 用 asyncio.run 驱动。覆盖：开场 + P1 安全网武装、
开场门控/看门狗（反馈①）、P1 宣告短语检测→延迟到 turn_complete 才进备题（末问不被
吞 / UI 后于宣告）、备题倒计时延迟到念题轮说完（反馈②，含念题兜底 / 抢按 ready）、
ready 与计时器结束备题、P2→P3 短语检测（含拓宽变体 + p1 不误跳，反馈③）、P3 收尾
短语检测→done（含变体 + done 停输入，反馈④）、defer（检测只种 _pending，
turn_complete 才转）、空轮 / 打断轮不兑现、各段安全网强制转场（含 review W1 防自
取消）、计时器取消（看门狗 + 备题 + 安全网）。
"""

import asyncio

import pytest

import app.live.director as director_module
from app.live.director import PREP_SECONDS, IeltsDirector

CARD = {
    "id": "p2-01",
    "text": "Describe a skill you would like to learn.",
    "bullets": ["what", "why", "how", "and explain"],
}


class FakeWs:
    def __init__(self):
        self.events: list[dict] = []
        self.audio: list[bytes] = []

    async def send_json(self, payload):
        self.events.append(payload)

    async def send_bytes(self, data):
        self.audio.append(data)


class FakeSession:
    def __init__(self):
        self.directions: list = []

    async def send_client_content(self, *, turns, turn_complete=True):
        self.directions.append(turns.parts[0].text)


class YieldingWs(FakeWs):
    async def send_json(self, payload):
        await asyncio.sleep(0)            # 真让出事件循环（暴露计时器自取消）
        self.events.append(payload)


class YieldingSession(FakeSession):
    async def send_client_content(self, *, turns, turn_complete=True):
        await asyncio.sleep(0)
        self.directions.append(turns.parts[0].text)


def _new(yielding=False):
    if yielding:
        return IeltsDirector(CARD), YieldingWs(), YieldingSession()
    return IeltsDirector(CARD), FakeWs(), FakeSession()


async def _spoken_turn(d, ws, sess, transcript=""):
    """模拟一轮真实考官发言：有音频帧 + 可选转写，后 turn_complete。"""
    d.on_model_audio()
    if transcript:
        d.on_examiner_transcript(transcript)
    await d.on_turn_complete(ws, sess)


async def _to_p2_prep(d, ws, sess):
    """跑到 p2_prep 且倒计时已起跳：P1 问答 → P1 收尾宣告 → 念题轮说完。"""
    await _spoken_turn(d, ws, sess, "What is your hometown?")
    await _spoken_turn(d, ws, sess, "Thank you. That is the end of Part 1.")
    await _spoken_turn(d, ws, sess, "Here is your topic. Your preparation time starts now.")


def test_start_announces_p1_directs_opening_arms_fallback():
    d, ws, sess = _new()
    asyncio.run(d.start(ws, sess))
    assert ws.events == [{"type": "part_change", "part": "p1"}]
    assert len(sess.directions) == 1 and "Part 1" in sess.directions[0]
    assert d.state == "p1"
    assert d.input_paused is True                    # 开场门控：积压帧/杂音全丢（反馈①）
    assert d._opening_task is not None               # 开场看门狗已武装
    assert d._fallback_task is not None              # P1 安全网已武装
    d.cancel_timers()


def test_opening_gate_releases_after_first_spoken_turn():
    # 反馈①：开场门控只放行于首个**有声** turn_complete——空回执轮不算开场说完
    d, ws, sess = _new()

    async def run():
        await d.start(ws, sess)
        await d.on_turn_complete(ws, sess)            # 空回执轮（指令回执）：不放行
        assert d.input_paused is True
        await _spoken_turn(d, ws, sess, "Hello. Could you tell me your full name?")
        assert d.input_paused is False                # 开场真说完才归还麦克风
        assert d._opening_gate is False
        assert d._opening_task is None                # 看门狗随之撤销

    asyncio.run(run())
    d.cancel_timers()


def test_opening_turn_phrases_do_not_transition():
    # review W1：开场轮（门控未放行）整轮不做短语检测——模型开场讲解考试结构
    # 提到 "the end of Part 1" 绝不能把 P1 整段跳掉
    d, ws, sess = _new()

    async def run():
        await d.start(ws, sess)
        ws.events.clear()
        d.on_model_audio()
        d.on_examiner_transcript(
            "Hello. After the end of Part 1 you will receive a cue card. "
            "Could you tell me your name?"
        )
        assert d._pending is None                     # 开场轮不种 pending
        await d.on_turn_complete(ws, sess)            # 开场说完：只放行门控
        assert d.state == "p1" and d.input_paused is False
        # 门控放行后检测恢复正常：真宣告照常进备题
        await _spoken_turn(d, ws, sess, "Thank you. That is the end of Part 1.")
        assert d.state == "p2_prep"

    asyncio.run(run())
    d.cancel_timers()


def test_opening_watchdog_resends_when_silent(monkeypatch):
    # 反馈①另一半：开场指令被吞（迟迟无考官音频）→ 看门狗重发；听到声音即停
    monkeypatch.setattr(director_module, "OPENING_NUDGE_S", 0.01)
    d, ws, sess = _new()

    async def run():
        await d.start(ws, sess)
        await asyncio.sleep(0.05)                     # 看门狗到点 ≥1 次
        assert len(sess.directions) >= 2              # 开场指令被重发
        assert all("Begin the exam" in t for t in sess.directions)
        d.on_model_audio()                            # 首帧考官音频到达
        sent = len(sess.directions)
        await asyncio.sleep(0.05)
        assert len(sess.directions) == sent           # 听到声音后不再重发

    asyncio.run(run())
    d.cancel_timers()


def test_p1_ordinary_question_does_not_transition():
    d, ws, sess = _new()
    asyncio.run(_spoken_turn(d, ws, sess, "Do you work or study?"))
    assert d.state == "p1"                            # 无宣告短语 → 不转
    assert ws.events == []


def test_p1_end_phrase_defers_then_enters_prep():
    d, ws, sess = _new()

    async def run():
        await _spoken_turn(d, ws, sess, "What do you do?")
        assert d.state == "p1"
        # 宣告轮：检测到短语只种 _pending，turn_complete 才兑现
        d.on_model_audio()
        d.on_examiner_transcript("Thank you. That is the end of Part 1.")
        assert d._pending is not None and d.state == "p1"   # defer：尚未转场
        assert d.input_paused is False                       # 末答此前已自然收口
        await d.on_turn_complete(ws, sess)                   # 宣告说完 → 进备题
        # 反馈②：cue card 立即弹（随念题同屏），倒计时此刻还没起跳
        assert d.state == "p2_prep" and d.input_paused is True
        assert d._prep_pending is True and d._prep_task is None
        kinds = [e["type"] for e in ws.events]
        assert kinds == ["part_change", "present_cue_card"]
        # 念题轮说完（"...starts now."）→ 倒计时才起跳
        await _spoken_turn(d, ws, sess, "Here is your topic. Your preparation time starts now.")
        assert d._prep_pending is False and d._prep_task is not None

    asyncio.run(run())
    kinds = [e["type"] for e in ws.events]
    assert kinds == ["part_change", "present_cue_card", "start_prep_timer"]
    assert ws.events[0]["part"] == "p2_prep"
    assert ws.events[1]["card"]["id"] == "p2-01"
    assert ws.events[1]["card"]["bullets"] == CARD["bullets"]
    assert ws.events[2]["seconds"] == PREP_SECONDS
    assert any(CARD["text"] in t for t in sess.directions)   # 念我们选定的题
    d.cancel_timers()


def test_ready_during_cue_reading_defers_until_cue_spoken():
    # 反馈②边角：念题期抢按 ready（倒计时未起跳）→ 记下不立即转（防与念题生成流
    # 绞缠），念题轮说完直接进长谈、全程不发 start_prep_timer
    d, ws, sess = _new()

    async def run():
        await _spoken_turn(d, ws, sess, "Thank you. That is the end of Part 1.")
        assert d.state == "p2_prep" and d._prep_pending is True
        await d.on_ready(ws, sess)                    # 抢按：不立即转
        assert d.state == "p2_prep" and d._ready_early is True
        await _spoken_turn(d, ws, sess, "Here is your topic.")   # 念题轮说完
        assert d.state == "p2_talk" and d.input_paused is False

    asyncio.run(run())
    assert not any(e["type"] == "start_prep_timer" for e in ws.events)
    assert any("long turn" in t for t in sess.directions)
    d.cancel_timers()


def test_cue_read_fallback_starts_countdown(monkeypatch):
    # 反馈②兜底：念题轮迟迟不 turn_complete（指令/生成丢失）→ MAX_CUE_READ_S
    # 到点倒计时照样起跳，备题不卡死
    monkeypatch.setattr(director_module, "MAX_CUE_READ_S", 0.01)
    d, ws, sess = _new(yielding=True)

    async def run():
        await _spoken_turn(d, ws, sess, "Thank you. That is the end of Part 1.")
        assert d.state == "p2_prep" and d._prep_task is None
        await asyncio.sleep(0.05)                     # 念题兜底到点
        assert d._prep_pending is False and d._prep_task is not None

    asyncio.run(run())
    assert any(e["type"] == "start_prep_timer" for e in ws.events)
    d.cancel_timers()


def test_interrupted_keeps_prep_pending():
    # 念题轮被打断（在途残帧触发 VAD）→ _prep_pending 是位置标记不是宣告，
    # 不随 on_interrupted 清掉；下一有声轮照样起跳倒计时
    d, ws, sess = _new()

    async def run():
        await _spoken_turn(d, ws, sess, "Thank you. That is the end of Part 1.")
        assert d._prep_pending is True
        d.on_model_audio()
        d.on_interrupted()                            # 念题轮被打断
        assert d._prep_pending is True
        await _spoken_turn(d, ws, sess, "Here is your topic once more.")
        assert d._prep_task is not None               # 倒计时照样起跳

    asyncio.run(run())
    d.cancel_timers()


def test_ready_ends_prep_once():
    d, ws, sess = _new()

    async def run():
        await _to_p2_prep(d, ws, sess)
        ws.events.clear(); sess.directions.clear()
        await d.on_ready(ws, sess)                    # 提前结束备题
        assert d.state == "p2_talk" and d.input_paused is False
        await d.on_ready(ws, sess)                    # 二次 ready：查重无副作用

    asyncio.run(run())
    assert ws.events == [{"type": "part_change", "part": "p2_talk"}]
    assert len(sess.directions) == 1
    assert "long turn" in sess.directions[0]
    d.cancel_timers()                                 # 清 P2 安全网


def test_prep_timer_fires_when_no_ready(monkeypatch):
    monkeypatch.setattr(director_module, "PREP_SECONDS", 0.01)
    d, ws, sess = _new()

    async def run():
        await _to_p2_prep(d, ws, sess)
        await asyncio.sleep(0.05)                     # 计时器到点

    asyncio.run(run())
    assert d.state == "p2_talk" and d.input_paused is False
    d.cancel_timers()


def test_p2_to_p3_phrase_enters_p3():
    d, ws, sess = _new()
    d.state = "p2_talk"

    async def run():
        await _spoken_turn(d, ws, sess, "Why did you choose it?")   # 追问，不转
        assert d.state == "p2_talk"
        await _spoken_turn(
            d, ws, sess,
            "Thank you. I would now like to discuss some more general questions. "
            "How has technology changed learning?",
        )

    asyncio.run(run())
    assert d.state == "p3"
    assert {"type": "part_change", "part": "p3"} in ws.events
    d.cancel_timers()                                 # 清 P3 安全网


def test_p2_to_p3_variant_phrases_enter_p3():
    # 反馈③：模型常不逐字念剧本宣告——拓宽后的变体锚都要能接住
    for phrase in (
        "Thank you. Let's move on to Part 3 now. Why do people value skills?",
        "We have been talking about a skill you want to learn. Why is it useful?",
        "We've been talking about this topic. Let us discuss it more broadly.",
    ):
        d, ws, sess = _new()
        d.state = "p2_talk"
        asyncio.run(_spoken_turn(d, ws, sess, phrase))
        assert d.state == "p3", phrase
        d.cancel_timers()


def test_followup_you_have_been_talking_does_not_enter_p3():
    # review W2：追问常以 "You've been talking about..." 开场——裸 "been talking
    # about" 锚会把追问轮误判成 P2→P3 宣告，必须带 we 前缀才认
    d, ws, sess = _new()
    d.state = "p2_talk"
    asyncio.run(
        _spoken_turn(d, ws, sess, "You've been talking about music. What inspired you?")
    )
    assert d.state == "p2_talk"


def test_p3_jump_from_p2_prep_cancels_prep_timer():
    # review S1：备题中模型直接转 P3（不走完备题）——_clear_prep 撤计时器 + 归还输入
    d, ws, sess = _new()

    async def run():
        await _to_p2_prep(d, ws, sess)               # 倒计时已起跳
        assert d._prep_task is not None
        await _spoken_turn(
            d, ws, sess, "I would now like to discuss some more general questions."
        )
        assert d.state == "p3"
        assert d._prep_task is None and d.input_paused is False

    asyncio.run(run())
    d.cancel_timers()


def test_p1_mention_of_part_three_does_not_jump():
    # 反馈③的反向护栏：P2→P3 锚已拓宽到 "part 3" 等较泛短语，必须只在 p2_* 态认；
    # 开场闲聊讲解考试结构提到 Part 3 绝不能 p1 直跳 p3（cue card 会被整段跳掉）
    d, ws, sess = _new()
    asyncio.run(
        _spoken_turn(
            d, ws, sess,
            "This test has Part 1, Part 2 and Part 3. Could you tell me your name?",
        )
    )
    assert d.state == "p1"
    assert ws.events == []


def test_p3_closing_phrase_enters_done():
    d, ws, sess = _new()
    d.state = "p3"

    async def run():
        await _spoken_turn(d, ws, sess, "What about the future?")   # 普通 P3 问
        assert d.state == "p3"
        d.on_model_audio()
        d.on_examiner_transcript("Thank you. That is the end of the speaking test.")
        assert d._pending is not None and d.state == "p3"          # defer
        await d.on_turn_complete(ws, sess)

    asyncio.run(run())
    assert d.state == "done"
    assert d.input_paused is True                     # 反馈④：考后停输入（scoring mode）
    assert {"type": "part_change", "part": "done"} in ws.events


def test_closing_variant_phrases_enter_done():
    # 反馈③/④：模型收尾说法多变（end of Part 3 / end of the test / concludes…）——
    # 漏检即永不收官，变体都要能接住
    for phrase in (
        "Thank you. That is the end of Part 3.",
        "That is the end of the test. Goodbye.",
        "This concludes the speaking test. Well done.",
    ):
        d, ws, sess = _new()
        d.state = "p3"
        asyncio.run(_spoken_turn(d, ws, sess, phrase))
        assert d.state == "done", phrase
        assert d.input_paused is True


def test_closing_phrase_from_p2_talk_enters_done():
    # 实测实锤：模型在 p2_talk 直接说收尾、跳过 P3 宣告——收尾必须全状态可检测，
    # 否则 director 卡在 p2_talk（线上真发生过）
    d, ws, sess = _new()
    d.state = "p2_talk"

    async def run():
        await _spoken_turn(d, ws, sess, "Do you think technology has downsides?")  # P3 风格问，不收
        assert d.state == "p2_talk"
        d.on_model_audio()
        d.on_examiner_transcript("Thank you. That is the end of the speaking test.")
        assert d._pending is not None                # p2_talk 也认收尾
        await d.on_turn_complete(ws, sess)

    asyncio.run(run())
    assert d.state == "done"
    assert {"type": "part_change", "part": "done"} in ws.events


def test_closing_from_p2_prep_clears_prep_and_pauses_input():
    # 极端跳段：备题中考官就说收尾——_enter_done 经 _clear_prep 撤备题计时器，
    # 随后重新停输入（done = scoring mode，反馈④；不是备题闸门的残留）
    d, ws, sess = _new()

    async def run():
        await _to_p2_prep(d, ws, sess)
        assert d.state == "p2_prep" and d.input_paused is True
        d.on_model_audio()
        d.on_examiner_transcript("That is the end of the speaking test.")
        await d.on_turn_complete(ws, sess)
        assert d.state == "done"
        assert d.input_paused is True and d._prep_task is None

    asyncio.run(run())


def test_empty_turn_does_not_consume_pending():
    # 种下 _pending 后若来一个无音频回执轮——空轮门必须挡住，绝不提前兑现
    d, ws, sess = _new()

    async def run():
        d.on_examiner_transcript("That is the end of Part 1.")   # 种 pending（无音频）
        assert d._pending is not None
        await d.on_turn_complete(ws, sess)           # 空轮（_turn_had_audio False）→ 不兑现
        assert d.state == "p1" and d._pending is not None
        d.on_model_audio()                           # 真发声宣告轮
        await d.on_turn_complete(ws, sess)           # → 才兑现
        assert d.state == "p2_prep"

    asyncio.run(run())
    d.cancel_timers()


def test_empty_turn_complete_does_not_advance():
    # Live 偶发无音频 turn_complete（导演文本指令回执轮）——不兑现不推进
    d, ws, sess = _new()

    async def run():
        for _ in range(4):
            await d.on_turn_complete(ws, sess)       # 全是空轮
        assert d.state == "p1"
        # 即使空轮里"检测"到短语也不算（无音频不种 / 不兑现）
        d.on_examiner_transcript("end of part 1")
        await d.on_turn_complete(ws, sess)           # 仍无音频
        assert d.state == "p1"

    asyncio.run(run())
    d.cancel_timers()


def test_interrupted_clears_pending_and_transcript():
    # 宣告轮被打断（没说完整）→ 清 _pending，等考官重新宣告
    d, ws, sess = _new()

    async def run():
        d.on_model_audio()
        d.on_examiner_transcript("Thank you. That is the end of Part 1.")
        assert d._pending is not None
        d.on_interrupted()                           # 打断
        assert d._pending is None and d._turn_transcript == ""
        await d.on_turn_complete(ws, sess)           # 打断后的空回执 → 不转
        assert d.state == "p1"
        await _spoken_turn(d, ws, sess, "That is the end of Part 1.")   # 重新宣告
        assert d.state == "p2_prep"

    asyncio.run(run())
    d.cancel_timers()


def test_p1_fallback_forces_prep(monkeypatch):
    # P1 安全网：考官始终不说宣告句 → 兜底逼它说 + 种 _pending，下一轮兑现进备题。
    # Yielding 假体验证 force 路径经 _set_state→_cancel_fallback 不自取消（review W1）
    monkeypatch.setattr(director_module, "MAX_P1_S", 0.01)
    d, ws, sess = _new(yielding=True)

    async def run():
        await d.start(ws, sess)
        await asyncio.sleep(0.05)                     # 安全网到点：注入兜底提示 + 种 pending
        assert d.state == "p1" and d._pending is not None
        await _spoken_turn(d, ws, sess, "Thank you. That is the end of Part 1.")
        assert d.state == "p2_prep"
        await _spoken_turn(d, ws, sess, "Here is your topic.")   # 念题轮说完 → 倒计时

    asyncio.run(run())
    assert any("end of Part 1" in t for t in sess.directions)
    kinds = [e["type"] for e in ws.events]
    # 事件没被截断（反馈②时序：cue card 先、倒计时晚一拍）
    assert kinds[-3:] == ["part_change", "present_cue_card", "start_prep_timer"]
    d.cancel_timers()


def test_p2_talk_fallback_forces_p3(monkeypatch):
    # P2 长谈安全网：考官迟迟不转 P3 → 兜底逼它说转场句 + 种 _pending，下一轮进 p3。
    # Yielding 验证 force 路径 _set_state→_cancel_fallback 不自取消（review W1）
    monkeypatch.setattr(director_module, "MAX_P2_TALK_S", 0.01)
    d, ws, sess = _new(yielding=True)
    d.state = "p2_talk"

    async def run():
        d._arm_fallback(director_module.MAX_P2_TALK_S, d._force_enter_p3, ws, sess)
        await asyncio.sleep(0.05)                     # 安全网到点
        assert d.state == "p2_talk" and d._pending is not None
        await _spoken_turn(
            d, ws, sess,
            "Thank you. I would now like to discuss some more general questions. "
            "How important is lifelong learning?",
        )
        assert d.state == "p3"

    asyncio.run(run())
    assert any("more general questions" in t for t in sess.directions)
    d.cancel_timers()


def test_p3_fallback_forces_done(monkeypatch):
    monkeypatch.setattr(director_module, "MAX_P3_S", 0.01)
    d, ws, sess = _new(yielding=True)
    d.state = "p3"

    async def run():
        d._arm_fallback(director_module.MAX_P3_S, d._force_enter_done, ws, sess)
        await asyncio.sleep(0.05)                     # 安全网到点
        assert d.state == "p3" and d._pending is not None
        await _spoken_turn(d, ws, sess, "Thank you. That is the end of the speaking test.")
        assert d.state == "done"

    asyncio.run(run())
    assert any("end of the speaking test" in t for t in sess.directions)
    d.cancel_timers()


def test_cancel_timers_kills_prep_fallback_and_monologue():
    d, ws, sess = _new()

    async def run():
        await _to_p2_prep(d, ws, sess)               # p2_prep：prep_task 活
        prep = d._prep_task
        await d.on_ready(ws, sess)                    # p2_talk：fallback + 独白计时器活
        fb = d._fallback_task
        mono = d._monologue_task
        assert prep is not None and fb is not None and not fb.done()
        assert mono is not None and not mono.done()
        d.cancel_timers()
        await asyncio.sleep(0)
        assert prep.cancelled() and fb.cancelled() and mono.cancelled()
        assert d._prep_task is None and d._fallback_task is None
        assert d._monologue_task is None

    asyncio.run(run())


# —— P2 独白 2 分钟上限（IELTS_CASE §2 上限层，D1）—— #


async def _to_p2_talk_invited(d, ws, sess):
    """跑到 p2_talk 且邀请轮已说完（独白计时器锚定保持）。"""
    await _to_p2_prep(d, ws, sess)
    await d.on_ready(ws, sess)                        # → p2_talk，独白计时器武装
    await _spoken_turn(d, ws, sess, "Please begin your long turn now.")   # 邀请轮


def test_monologue_cap_injects_cut_prompt(monkeypatch):
    # 独白满上限考官仍未收口 → 注入切断指令（礼貌 Thank you + 追问），不转场
    monkeypatch.setattr(director_module, "MAX_MONOLOGUE_S", 0.02)
    d, ws, sess = _new(yielding=True)

    async def run():
        await _to_p2_talk_invited(d, ws, sess)
        assert d._monologue_task is not None and d._p2_invite_seen is True
        sess.directions.clear()
        await asyncio.sleep(0.06)                     # 上限到点
        assert any("Politely cut in" in t for t in sess.directions)
        assert d.state == "p2_talk"                   # 只注入不转场
        assert d._monologue_task.done()               # 任务自然完结（review S1）

    asyncio.run(run())
    d.cancel_timers()


def test_monologue_cap_disarmed_when_examiner_retakes_floor(monkeypatch):
    # 考官在邀请轮之后再次发声（软探询/追问）= 独白自然结束 → 计时器撤销，不再切断
    monkeypatch.setattr(director_module, "MAX_MONOLOGUE_S", 0.02)
    d, ws, sess = _new()

    async def run():
        await _to_p2_talk_invited(d, ws, sess)
        await _spoken_turn(d, ws, sess, "Why did you choose this skill?")   # 追问轮
        assert d._monologue_task is None              # 已撤销
        sess.directions.clear()
        await asyncio.sleep(0.06)
        assert sess.directions == []                  # 上限不再触发

    asyncio.run(run())
    d.cancel_timers()


def test_monologue_cap_cancelled_on_part_exit():
    # 宣告轮转出 p2_talk 后独白计时器不残留（同轮再发声撤销 + _set_state 离场双保险）
    d, ws, sess = _new()

    async def run():
        await _to_p2_talk_invited(d, ws, sess)
        assert d._monologue_task is not None
        await _spoken_turn(
            d, ws, sess,
            "Thank you. We have been talking about this topic. "
            "I would now like to discuss some more general questions related to it.",
        )
        assert d.state == "p3"
        assert d._monologue_task is None

    asyncio.run(run())
    d.cancel_timers()


def test_persona_pins_case_guardrails():
    # IELTS_CASE §3/§4 越界守则 persona pin（M1/M2）：spec 给定话术与关键规则不回潮
    # （折叠空白：persona 排版换行会把句子断在行中，子串按单行语义断言）
    p = " ".join(director_module.EXAMINER_SYSTEM_INSTRUCTION.split())
    assert "Could you say that in English?" in p          # §4 中文/求词（spec 逐字话术）
    assert "anything else you would like to add" in p.lower()   # §2 软探询（裁决层）
    assert "repeat it once" in p                          # §3 请求重复一次
    assert "I can't give a score during the exam." in p   # §4 中途问分数
    assert "the topic stays the same." in p               # §4 换题卡婉拒
    assert "never fill the silence" in p                  # §3 停顿不救场
    assert "one-word answer" in p                         # §3 弱答直接换题


def test_prep_timer_path_sends_full_transition(monkeypatch):
    # review W1：计时器路径绝不能自取消——转场事件与长谈指令必须完整发出
    monkeypatch.setattr(director_module, "PREP_SECONDS", 0.01)
    d, ws, sess = _new(yielding=True)

    async def run():
        await _to_p2_prep(d, ws, sess)
        await asyncio.sleep(0.1)                      # 计时器到点并跑完

    asyncio.run(run())
    assert d.state == "p2_talk"
    assert {"type": "part_change", "part": "p2_talk"} in ws.events
    assert any("long turn" in t for t in sess.directions)
    assert d._prep_task is None
    d.cancel_timers()


def test_done_state_ignores_further_turns():
    d, ws, sess = _new()
    d.state = "done"
    asyncio.run(_spoken_turn(d, ws, sess, "anything"))
    assert d.state == "done"
    assert ws.events == [] and sess.directions == []


def test_bridge_feeds_examiner_transcript_and_orders_events():
    # 桥级集成：output_transcription 喂 director 做检测（在 transcript_delta 之前），
    # turn_complete 兑现转场；同一 response 先 interrupted 后 turn_complete 顺序保持
    import asyncio as aio
    from types import SimpleNamespace
    from app.live.bridge import _pump_downstream

    d, ws, _ = _new()
    d.state = "p3"

    sc1 = SimpleNamespace(
        input_transcription=None,
        output_transcription=SimpleNamespace(text="Thank you. That is the end of the speaking test."),
        interrupted=False, turn_complete=False,
    )
    sc2 = SimpleNamespace(
        input_transcription=None, output_transcription=None,
        interrupted=False, turn_complete=True,
    )
    audio = SimpleNamespace(data=b"\x00\x01", server_content=None)   # 考官音频帧

    class Sess:
        def receive(self_inner):
            async def gen():
                yield audio                          # 标记本轮有音频
                yield SimpleNamespace(data=None, server_content=sc1)   # 转写 → 检测
                yield SimpleNamespace(data=None, server_content=sc2)   # turn_complete → 兑现
                raise RuntimeError("stop")

            return gen()

    async def run():
        try:
            await _pump_downstream(ws, Sess(), None, None, d)
        except RuntimeError:
            pass

    aio.run(run())
    assert d.state == "done"                          # 收尾短语经桥检测 + 兑现
    assert {"type": "part_change", "part": "done"} in ws.events


def test_bridge_processes_interrupted_before_turn_complete_same_response():
    # 同一 response 同时携带 interrupted + turn_complete（打断轮）——bridge 先清标
    # 后判空，被打断轮绝不兑现 _pending（桥级集成验证）
    import asyncio as aio
    from types import SimpleNamespace
    from app.live.bridge import _pump_downstream

    d, ws, _ = _new()
    d.on_model_audio()
    d.on_examiner_transcript("Thank you. That is the end of Part 1.")   # 已种 pending

    sc = SimpleNamespace(
        input_transcription=None, output_transcription=None,
        interrupted=True, turn_complete=True,
    )
    resp = SimpleNamespace(data=None, server_content=sc)

    class OneShotSession:
        def receive(self_inner):
            async def gen():
                yield resp
                raise RuntimeError("stop")

            return gen()

    async def run():
        try:
            await _pump_downstream(ws, OneShotSession(), None, None, d)
        except RuntimeError:
            pass

    aio.run(run())
    assert d.state == "p1" and d._pending is None     # 打断清掉 pending，没转场
    kinds = [e["type"] for e in ws.events]
    assert kinds == ["interrupted", "turn_complete"]
