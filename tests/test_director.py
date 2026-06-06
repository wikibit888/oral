"""方式 A 导演状态机单测（ws / session 皆假体，零网络；async 用 asyncio.run 驱动）。

覆盖：开场、P1 计数转备题（事件三连 + 输入暂停 + 计时器）、ready 提前结束备题
（含查重防双触发）、计时器到点路径、长谈邀请轮不转场 / 追问轮转场、追问→P3、
P3 计数收尾、计时器取消。
"""

import asyncio

import pytest

import app.live.director as director_module
from app.live.director import (
    P1_EXAMINER_TURNS,
    P3_EXAMINER_TURNS,
    PREP_SECONDS,
    IeltsDirector,
)

CARD = {
    "id": "p2-01",
    "text": "Describe a skill you would like to learn.",
    "bullets": ["what", "why", "how", "and explain"],
}


class FakeWs:
    def __init__(self):
        self.events: list[dict] = []

    async def send_json(self, payload):
        self.events.append(payload)


class FakeSession:
    def __init__(self):
        self.directions: list = []

    async def send_client_content(self, *, turns, turn_complete=True):
        self.directions.append(turns.parts[0].text)


def _new():
    return IeltsDirector(CARD), FakeWs(), FakeSession()


async def _spoken_turn(d, ws, sess):
    """模拟一轮真实考官发言：先有音频帧、后 turn_complete（空轮不计数）。"""
    d.on_model_audio()
    await d.on_turn_complete(ws, sess)


def test_start_announces_p1_and_directs_opening():
    d, ws, sess = _new()
    asyncio.run(d.start(ws, sess))
    assert ws.events == [{"type": "part_change", "part": "p1"}]
    assert len(sess.directions) == 1 and "Part 1" in sess.directions[0]
    assert d.state == "p1" and d.input_paused is False


def test_p1_turns_then_enter_prep():
    d, ws, sess = _new()

    async def run():
        for _ in range(P1_EXAMINER_TURNS - 1):
            await _spoken_turn(d, ws, sess)
            assert d.state == "p1"                       # 未满轮数不转
        await _spoken_turn(d, ws, sess)               # 满 → 备题

    asyncio.run(run())
    assert d.state == "p2_prep"
    assert d.input_paused is True                        # 备题期丢帧
    kinds = [e["type"] for e in ws.events]
    assert kinds == ["part_change", "present_cue_card", "start_prep_timer"]
    assert ws.events[1]["card"]["id"] == "p2-01"
    assert ws.events[1]["card"]["bullets"] == CARD["bullets"]
    assert ws.events[2]["seconds"] == PREP_SECONDS
    assert any(CARD["text"] in t for t in sess.directions)   # 考官念主题
    d.cancel_timers()


def test_ready_ends_prep_once():
    d, ws, sess = _new()

    async def run():
        for _ in range(P1_EXAMINER_TURNS):
            await _spoken_turn(d, ws, sess)
        ws.events.clear(); sess.directions.clear()
        await d.on_ready(ws, sess)                       # 提前结束备题
        assert d.state == "p2_talk" and d.input_paused is False
        await d.on_ready(ws, sess)                       # 二次 ready：查重无副作用

    asyncio.run(run())
    assert ws.events == [{"type": "part_change", "part": "p2_talk"}]
    assert len(sess.directions) == 1
    assert "follow-up question" in sess.directions[0]    # 追问预埋在邀请提示里


def test_prep_timer_fires_when_no_ready(monkeypatch):
    monkeypatch.setattr(director_module, "PREP_SECONDS", 0.01)
    d, ws, sess = _new()

    async def run():
        for _ in range(P1_EXAMINER_TURNS):
            await _spoken_turn(d, ws, sess)
        await asyncio.sleep(0.05)                        # 计时器到点

    asyncio.run(run())
    assert d.state == "p2_talk" and d.input_paused is False


def test_talk_invitation_turn_does_not_advance_followup_turn_does():
    d, ws, sess = _new()
    d.state = "p2_talk"

    async def run():
        await _spoken_turn(d, ws, sess)               # 第 1 轮 = 开始邀请
        assert d.state == "p2_talk"
        await _spoken_turn(d, ws, sess)               # 第 2 轮 = 追问问出

    asyncio.run(run())
    assert d.state == "p2_followup"
    assert any("Part 3" in t for t in sess.directions)   # 收追问+转 P3 已预埋


def test_followup_turn_enters_p3_then_counts_to_done():
    d, ws, sess = _new()
    d.state = "p2_followup"

    async def run():
        await _spoken_turn(d, ws, sess)               # 收追问 + P3 开场问
        assert d.state == "p3"
        for _ in range(P3_EXAMINER_TURNS - 1):
            await _spoken_turn(d, ws, sess)
            assert d.state == "p3"
        await _spoken_turn(d, ws, sess)               # 满 → 收尾

    asyncio.run(run())
    assert d.state == "done"
    assert any("exam is over" in t for t in sess.directions)


def test_cancel_timers_kills_prep_task():
    d, ws, sess = _new()

    async def run():
        for _ in range(P1_EXAMINER_TURNS):
            await _spoken_turn(d, ws, sess)
        task = d._prep_task
        assert task is not None and not task.done()
        d.cancel_timers()
        await asyncio.sleep(0)                            # 让取消落地
        assert task.cancelled()
        assert d._prep_task is None

    asyncio.run(run())


def test_done_state_ignores_further_turns():
    d, ws, sess = _new()
    d.state = "done"
    d.on_model_audio()
    asyncio.run(d.on_turn_complete(ws, sess))             # 收尾轮自身的 turn_complete
    assert d.state == "done"
    assert ws.events == [] and sess.directions == []


def test_empty_turn_complete_does_not_advance():
    # 真冒烟实锤：Live 偶发无音频的 turn_complete（导演文本指令的回执轮）——
    # 不计轮，否则 FSM 抢跑、指令堆进未完成生成流把会话卡死
    d, ws, sess = _new()

    async def run():
        for _ in range(P1_EXAMINER_TURNS * 2):
            await d.on_turn_complete(ws, sess)            # 全是空轮
        assert d.state == "p1"                            # 一步都不动
        d.on_model_audio()
        await d.on_turn_complete(ws, sess)                # 真发声轮才计 1
        assert d.state == "p1"

    asyncio.run(run())


def test_interrupted_clears_audio_flag_blocks_stale_count():
    # review C1：被打断轮残留的发声标记不得污染下一个空回执轮
    d, ws, sess = _new()

    async def run():
        d.on_model_audio()                                # 考官开口
        d.on_interrupted()                                # 用户打断（轮没有 turn_complete）
        await d.on_turn_complete(ws, sess)                # 空回执轮 → 不得计数
        assert d.state == "p1" and d._examiner_turns == 0
        d.on_model_audio()                                # 新的完整轮
        await d.on_turn_complete(ws, sess)
        assert d._examiner_turns == 1

    asyncio.run(run())


def test_prep_timer_path_sends_full_transition(monkeypatch):
    # review W1：计时器路径绝不能自取消——转场事件与长谈指令必须完整发出
    monkeypatch.setattr(director_module, "PREP_SECONDS", 0.01)

    class YieldingWs(FakeWs):
        async def send_json(self, payload):
            await asyncio.sleep(0)                        # 真让出事件循环（暴露自取消）
            self.events.append(payload)

    class YieldingSession(FakeSession):
        async def send_client_content(self, *, turns, turn_complete=True):
            await asyncio.sleep(0)
            self.directions.append(turns.parts[0].text)

    d, ws, sess = IeltsDirector(CARD), YieldingWs(), YieldingSession()

    async def run():
        for _ in range(P1_EXAMINER_TURNS):
            await _spoken_turn(d, ws, sess)
        await asyncio.sleep(0.1)                          # 计时器到点并跑完

    asyncio.run(run())
    assert d.state == "p2_talk"
    assert {"type": "part_change", "part": "p2_talk"} in ws.events   # 事件没被截断
    assert any("follow-up question" in t for t in sess.directions)   # 指令完整发出
    assert d._prep_task is None


def test_bridge_processes_interrupted_before_turn_complete_same_response():
    # 复审建议：同一 response 同时携带 interrupted + turn_complete（打断轮）——
    # bridge 顺序保证先清标后判空，被打断轮绝不计数（桥级集成验证）
    import asyncio as aio
    from types import SimpleNamespace
    from app.live.bridge import _pump_downstream

    d, ws, sess_unused = _new()
    d.on_model_audio()                                    # 考官已开口（打断前）

    sc = SimpleNamespace(
        input_transcription=None, output_transcription=None,
        interrupted=True, turn_complete=True,
    )
    resp = SimpleNamespace(data=None, server_content=sc)

    class OneShotSession:
        def receive(self_inner):
            async def gen():
                yield resp
                raise RuntimeError("stop")                # 结束泵循环

            return gen()

    async def run():
        try:
            await _pump_downstream(ws, OneShotSession(), None, None, d)
        except RuntimeError:
            pass

    aio.run(run())
    assert d.state == "p1" and d._examiner_turns == 0     # 打断轮没被计数
    kinds = [e["type"] for e in ws.events]
    assert kinds == ["interrupted", "turn_complete"]      # 事件顺序保持
