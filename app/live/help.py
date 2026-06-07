"""language_help tool 的会话内应答台（情景对话教练协议的结构化通道）。

模型自带翻译调用 language_help（声明见 scenario_cases.LANGUAGE_HELP_TOOL——
翻译不在代码侧做：Live 模型自己就是最好的带语境翻译器，tool 若再外呼模型，
等待期间考官是哑的）。本台只做三件事，纯本地、零外呼、瞬时返回：

①结构化转发：求助参数原样发前端 `teaching` 事件（卡片 UI / 日志），
  方案里的 teaching[] 字段在 Live 架构下的落点；
②模板控形：按 kind 查指令模板并**确定性轮换**（防生硬重复，同 openers
  的"不重样"思路，但轮换可测）；
③连续求助控频：窗口内连续第 N 次起换「鼓励先自己试」指令
  （SCENARIO_CASE.md A4 的「查词典模式」风险在代码里硬解）。

仅情景对话接线（live_ws）；方式 A 考官不声明 tools，保持中立零破壁。
"""

import logging
import time
from contextlib import suppress

from app.scenario_cases import CASES, HELP_DIRECTIVES, HELP_OVERUSE_DIRECTIVE

logger = logging.getLogger(__name__)

HELP_STREAK_WINDOW_S = 90   # 距上次求助 < 此窗口算"连续"（否则计数重置）
HELP_OVERUSE_THRESHOLD = 3  # 连续第 N 次求助起，改发「鼓励先自己试」指令

_FALLBACK_KIND = "explicit_ask"   # 模型传了枚举外的 kind 时按显式求助应答


class LanguageHelpDesk:
    """单次情景会话的求助应答台。状态只在事件循环线程被触碰（无锁）。

    on_tool_call 由 bridge 下行泵在收到 tool_call 时 await——返回值即
    send_tool_response 的 response 体：{"directive": 指令文本}，模型照指令
    把帮助织进语音（模板定风格骨架，话由模型自己装）。

    case 感知：指令模板的 {scene} 槽填该 case 的 scene_label（回场景锚点带
    具体场景）；teaching 事件带 case 字段（前端卡片可按场景渲染）。
    """

    def __init__(self, websocket, case: str, *, clock=time.monotonic):
        self._ws = websocket
        self._case = case
        # 入口已按白名单守门（live_ws._parse_params），这里直查快败
        self._scene = CASES[case].scene_label
        self._clock = clock         # 可注入假钟（控频测试确定性）
        self._count = 0             # 累计求助次数：模板轮换游标
        self._streak = 0            # 连续求助计数：控频判据
        self._last_at: float | None = None

    async def on_tool_call(self, name: str, args: dict) -> dict:
        """处理一次模型 tool 调用，返回 tool response 体（必须瞬时，无外呼）。

        未知工具名（模型幻觉）返回错误体不抛——宁可模型收到 error 后自行圆场，
        也不让整条会话因一次幻觉调用崩掉。
        """
        if name != "language_help":
            logger.warning("help: 未知 tool 调用被拒：%s", name)
            return {"error": f"unknown tool: {name}"}
        kind = args.get("kind")
        if kind not in HELP_DIRECTIVES:
            logger.warning("help: 枚举外 kind=%r，按 %s 应答", kind, _FALLBACK_KIND)
            kind = _FALLBACK_KIND
        english = args.get("english") or ""
        example = args.get("example") or ""
        directive = self._pick_directive(kind, english, example)
        # teaching 事件 best-effort：WS 已死说明会话正收束，不能连累 tool 响应
        # （模型还在等 send_tool_response，泵随取消收场）
        with suppress(Exception):
            await self._ws.send_json(
                {
                    "type": "teaching",
                    "case": self._case,
                    "kind": kind,
                    "chinese": args.get("chinese") or "",
                    "english": english,
                    "example": example,
                }
            )
        return {"directive": directive}

    def _pick_directive(self, kind: str, english: str, example: str) -> str:
        """控频 + 轮换选指令模板，填入模型给的词/例句 + 当前场景标签。

        用 replace 不用 str.format：english/example 是模型产出，含花括号时
        format 会 KeyError 炸泵。{scene} 先填——场景标签是受控文本，
        不会撞模型产出里的字面槽位。
        """
        now = self._clock()
        in_window = self._last_at is not None and now - self._last_at < HELP_STREAK_WINDOW_S
        self._streak = self._streak + 1 if in_window else 1
        self._last_at = now
        self._count += 1
        if self._streak >= HELP_OVERUSE_THRESHOLD:
            template = HELP_OVERUSE_DIRECTIVE
        else:
            variants = HELP_DIRECTIVES[kind]
            template = variants[(self._count - 1) % len(variants)]
        return (
            template.replace("{scene}", self._scene)
            .replace("{english}", english)
            .replace("{example}", example)
        )
