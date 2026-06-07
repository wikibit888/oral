"""情景教练运行时单测：LanguageHelpDesk（模板控形 / 轮换 / 控频 / teaching 事件 /
容错）+ ScenarioNudger（分级注入 / 防抖 / stage 钳制）。

ws / session / 时钟都注入假体，零网络；async 用 asyncio.run 驱动
（同 test_director 模式），控频与防抖用假钟拨表确定性复现。
"""

import asyncio

import pytest

from app.live.help import (
    GRAMMAR_SPEAK_GAP_S,
    HELP_OVERUSE_THRESHOLD,
    HELP_STREAK_WINDOW_S,
    NUDGE_DEBOUNCE_S,
    LanguageHelpDesk,
    ScenarioNudger,
)
from app.scenario_cases import (
    CASES,
    GRAMMAR_AFTER_HELP_DIRECTIVE,
    GRAMMAR_SILENT_DIRECTIVE,
    GRAMMAR_SPEAK_DIRECTIVES,
    HELP_DIRECTIVES,
    HELP_OVERUSE_DIRECTIVE,
    NUDGE_DIRECTIVES,
)

_SCENE = CASES["ordering"].scene_label


def _fill(template, english="spaghetti", example="Could I get the spaghetti, please?"):
    """与应答台同序填槽，构造期望 directive。"""
    return (
        template.replace("{scene}", _SCENE)
        .replace("{english}", english)
        .replace("{example}", example)
    )


class FakeWs:
    def __init__(self, *, broken=False):
        self.events: list = []
        self._broken = broken

    async def send_json(self, payload):
        if self._broken:
            raise RuntimeError("ws closed")
        self.events.append(payload)


class FakeClock:
    """手动拨表的单调钟。"""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _desk(ws=None, clock=None, case="ordering"):
    return LanguageHelpDesk(ws or FakeWs(), case, clock=clock or FakeClock())


def _args(**overrides):
    base = {
        "kind": "mixed_cn",
        "chinese": "意大利面",
        "english": "spaghetti",
        "example": "Could I get the spaghetti, please?",
    }
    base.update(overrides)
    return base


def test_directive_filled_and_teaching_event():
    ws = FakeWs()
    desk = _desk(ws)
    result = asyncio.run(desk.on_tool_call("language_help", _args()))
    # directive：模板槽位已填模型传来的翻译，无残留花括号槽
    assert "spaghetti" in result["directive"]
    assert "{english}" not in result["directive"]
    assert "{example}" not in result["directive"]
    assert "{scene}" not in result["directive"]
    # teaching 事件结构化转发（前端卡片）
    assert ws.events == [
        {
            "type": "teaching",
            "case": "ordering",
            "kind": "mixed_cn",
            "chinese": "意大利面",
            "english": "spaghetti",
            "example": "Could I get the spaghetti, please?",
        }
    ]


def test_directive_rotates_between_calls():
    async def run():
        clock = FakeClock()
        desk = _desk(clock=clock)
        first = await desk.on_tool_call("language_help", _args())
        clock.advance(HELP_STREAK_WINDOW_S + 1)   # 隔窗：不触发控频，纯测轮换
        second = await desk.on_tool_call("language_help", _args())
        assert first["directive"] != second["directive"]

    asyncio.run(run())


@pytest.mark.parametrize("kind", sorted(HELP_DIRECTIVES))
def test_each_kind_resolves_its_templates(kind):
    result = asyncio.run(_desk().on_tool_call("language_help", _args(kind=kind)))
    assert result["directive"] in [_fill(t) for t in HELP_DIRECTIVES[kind]]


def test_overuse_streak_switches_to_encourage_directive():
    async def run():
        clock = FakeClock()
        desk = _desk(clock=clock)
        expected = _fill(HELP_OVERUSE_DIRECTIVE)
        for i in range(HELP_OVERUSE_THRESHOLD - 1):   # 窗口内前 N-1 次：正常指令
            result = await desk.on_tool_call("language_help", _args())
            assert result["directive"] != expected, i
            clock.advance(5)
        result = await desk.on_tool_call("language_help", _args())   # 第 N 次：控频
        assert result["directive"] == expected

    asyncio.run(run())


def test_streak_resets_outside_window():
    async def run():
        clock = FakeClock()
        desk = _desk(clock=clock)
        for _ in range(HELP_OVERUSE_THRESHOLD - 1):
            await desk.on_tool_call("language_help", _args())
            clock.advance(5)
        clock.advance(HELP_STREAK_WINDOW_S)        # 出窗：连续计数重置
        result = await desk.on_tool_call("language_help", _args())
        assert result["directive"] != _fill(HELP_OVERUSE_DIRECTIVE)

    asyncio.run(run())


def test_unknown_tool_name_returns_error_without_event():
    ws = FakeWs()
    result = asyncio.run(_desk(ws).on_tool_call("hack_the_planet", _args()))
    assert "error" in result and "directive" not in result
    assert ws.events == []                     # 幻觉调用不发 teaching 卡片


def test_unknown_kind_falls_back():
    result = asyncio.run(_desk().on_tool_call("language_help", _args(kind="bogus")))
    assert "spaghetti" in result["directive"]  # 按 explicit_ask 兜底应答


def test_broken_ws_does_not_break_tool_response():
    # teaching 事件 best-effort：WS 已死也必须把 directive 回给模型
    result = asyncio.run(
        _desk(FakeWs(broken=True)).on_tool_call("language_help", _args())
    )
    assert "spaghetti" in result["directive"]


# —— grammar_note（B1 语法纠错：检出归模型，呈现归控频三态）—— #


def _gargs(**overrides):
    base = {"original": "I go yesterday", "fixed": "I went yesterday", "note": "past tense"}
    base.update(overrides)
    return base


def _gfill(template, fixed="I went yesterday", original="I go yesterday"):
    return (
        template.replace("{scene}", _SCENE)
        .replace("{fixed}", fixed)
        .replace("{original}", original)
    )


def test_grammar_speaks_up_front_and_sends_correction_event():
    async def run():
        ws = FakeWs()
        desk = _desk(ws)
        result = await desk.on_tool_call("grammar_note", _gargs())
        # 单独出现：回答最前对照纠正（say {fixed}, not {original}），首条用变体[0]
        assert result["directive"] == _gfill(GRAMMAR_SPEAK_DIRECTIVES[0])
        assert "I went yesterday" in result["directive"]
        assert "I go yesterday" in result["directive"]
        assert ws.events == [
            {
                "type": "correction",
                "case": "ordering",
                "original": "I go yesterday",
                "fixed": "I went yesterday",
                "note": "past tense",
                "spoken": True,
            }
        ]

    asyncio.run(run())


def test_grammar_after_chinese_help_same_turn():
    # 与中文求助同轮（explicit_ask）：纠正放中文应答之后（用户决策），照常口头
    async def run():
        clock = FakeClock()
        ws = FakeWs()
        desk = _desk(ws, clock)
        await desk.on_tool_call("language_help", _args(kind="explicit_ask"))
        clock.advance(1)                      # 同轮窗口内（批内连发）
        result = await desk.on_tool_call("grammar_note", _gargs())
        assert result["directive"] == _gfill(GRAMMAR_AFTER_HELP_DIRECTIVE)
        assert ws.events[-1]["spoken"] is True

    asyncio.run(run())


def test_grammar_before_language_help_speaks_up_front():
    # 契约顺序：grammar_note 先于 language_help 到达（声明要求 call BEFORE
    # speaking）——此时无同轮求助记录，走「回答最前」而非 after-help
    async def run():
        clock = FakeClock()
        desk = _desk(clock=clock)
        result = await desk.on_tool_call("grammar_note", _gargs())
        assert result["directive"] == _gfill(GRAMMAR_SPEAK_DIRECTIVES[0])
        clock.advance(1)
        help_result = await desk.on_tool_call(
            "language_help", _args(kind="explicit_ask")
        )
        assert "directive" in help_result      # 求助照常应答，互不干扰

    asyncio.run(run())


def test_grammar_same_turn_window_consumed_once():
    # 同轮钟用后即耗（review W1）：一次 language_help 只配对一次 grammar_note——
    # 窗口期内的第二条不再继承 mixed_cn 静默（首条 silent 未占间隔闸，故应口头）
    async def run():
        clock = FakeClock()
        desk = _desk(clock=clock)
        await desk.on_tool_call("language_help", _args(kind="mixed_cn"))
        clock.advance(1)
        first = await desk.on_tool_call("grammar_note", _gargs())
        assert first["directive"] == _gfill(GRAMMAR_SILENT_DIRECTIVE)   # recast 覆盖
        clock.advance(1)                          # 仍在 5s 窗口内
        second = await desk.on_tool_call("grammar_note", _gargs(note="article"))
        assert second["directive"] == _gfill(GRAMMAR_SPEAK_DIRECTIVES[0])  # 不被误静默

    asyncio.run(run())


def test_grammar_silent_when_mixed_cn_recast_covers_it():
    # mixed_cn 同轮：recast 重述天然已纠正，口头静默但事件照发（确认的边际 #3）
    async def run():
        clock = FakeClock()
        ws = FakeWs()
        desk = _desk(ws, clock)
        await desk.on_tool_call("language_help", _args(kind="mixed_cn"))
        clock.advance(1)
        result = await desk.on_tool_call("grammar_note", _gargs())
        assert result["directive"] == _gfill(GRAMMAR_SILENT_DIRECTIVE)
        correction = ws.events[-1]
        assert correction["type"] == "correction" and correction["spoken"] is False

    asyncio.run(run())


def test_grammar_speak_gap_silences_followup():
    # 间隔闸：45s 内第二条口头压掉（兼「每轮 ≤1」近似），事件照发
    async def run():
        clock = FakeClock()
        ws = FakeWs()
        desk = _desk(ws, clock)
        first = await desk.on_tool_call("grammar_note", _gargs())
        assert first["directive"] == _gfill(GRAMMAR_SPEAK_DIRECTIVES[0])
        clock.advance(GRAMMAR_SPEAK_GAP_S - 1)
        second = await desk.on_tool_call("grammar_note", _gargs(note="word choice"))
        assert second["directive"] == _gfill(GRAMMAR_SILENT_DIRECTIVE)
        assert ws.events[-1]["spoken"] is False
        clock.advance(2)                      # 出闸恢复口头；第二次口头轮换到变体[1]
        third = await desk.on_tool_call("grammar_note", _gargs(note="word choice"))
        assert third["directive"] == _gfill(GRAMMAR_SPEAK_DIRECTIVES[1])

    asyncio.run(run())


def test_grammar_missing_args_safe():
    result = asyncio.run(_desk().on_tool_call("grammar_note", {}))
    assert "directive" in result               # 缺参不崩，空串填槽


# —— ScenarioNudger（D1 沉默分级探询执行端）—— #


class FakeSession:
    """记录舞台指令注入（send_stage_direction → send_client_content）。"""

    def __init__(self):
        self.directions: list = []

    async def send_client_content(self, *, turns, turn_complete=True):
        self.directions.append(turns.parts[0].text)


def _nudger(clock=None, case="ordering"):
    return ScenarioNudger(case, clock=clock or FakeClock())


def test_nudge_injects_staged_directive_with_scene():
    async def run():
        clock = FakeClock()
        nudger = _nudger(clock)
        sess = FakeSession()
        for i, stage in enumerate((1, 2, 3)):
            clock.advance(NUDGE_DEBOUNCE_S + 1)
            await nudger.on_nudge(sess, stage)
            expected = NUDGE_DIRECTIVES[stage].replace("{scene}", _SCENE)
            assert sess.directions[i] == expected, stage
        # 分级语义：2 给句头、3 给选项并确认是否继续；全部无残留槽
        assert "starter" in sess.directions[1]
        assert "continue" in sess.directions[2]
        assert all("{" not in d for d in sess.directions)

    asyncio.run(run())


def test_nudge_debounced_within_window():
    async def run():
        clock = FakeClock()
        nudger = _nudger(clock)
        sess = FakeSession()
        await nudger.on_nudge(sess, 1)
        clock.advance(NUDGE_DEBOUNCE_S - 1)
        await nudger.on_nudge(sess, 2)       # 窗口内：忽略
        assert len(sess.directions) == 1
        clock.advance(2)
        await nudger.on_nudge(sess, 2)       # 出窗：放行
        assert len(sess.directions) == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    ("raw", "expected_stage"),
    [(0, 1), (-3, 1), (99, 3), ("2", 2), ("abc", 1), (None, 1)],
)
def test_nudge_stage_clamped_and_coerced(raw, expected_stage):
    # stage 是前端来的不可信输入：任何取值都不崩、钳到模板键域
    async def run():
        sess = FakeSession()
        await _nudger().on_nudge(sess, raw)
        assert sess.directions == [
            NUDGE_DIRECTIVES[expected_stage].replace("{scene}", _SCENE)
        ]

    asyncio.run(run())
