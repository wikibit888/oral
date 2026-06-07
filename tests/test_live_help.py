"""LanguageHelpDesk 应答台单测：模板控形 / 轮换 / 控频 / teaching 事件 / 容错。

ws 与时钟都注入假体，零网络；async 用 asyncio.run 驱动（同 test_director 模式），
控频用假钟拨表确定性复现。
"""

import asyncio

import pytest

from app.live.help import (
    HELP_OVERUSE_THRESHOLD,
    HELP_STREAK_WINDOW_S,
    LanguageHelpDesk,
)
from app.scenario_cases import CASES, HELP_DIRECTIVES, HELP_OVERUSE_DIRECTIVE

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
