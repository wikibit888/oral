"""情景对话教练协议的会话内运行时：language_help / grammar_note 应答台 + 沉默 nudge。

模型自带翻译调用 language_help（声明见 scenario_cases.LANGUAGE_HELP_TOOL——
翻译不在代码侧做：Live 模型自己就是最好的带语境翻译器，tool 若再外呼模型，
等待期间考官是哑的）。本台只做三件事，纯本地、零外呼、瞬时返回：

①结构化转发：求助参数原样发前端 `teaching` 事件（卡片 UI / 日志），
  方案里的 teaching[] 字段在 Live 架构下的落点；
②模板控形：按 kind 查指令模板并**确定性轮换**（防生硬重复，同 openers
  的"不重样"思路，但轮换可测）；
③连续求助控频：窗口内连续第 N 次起换「鼓励先自己试」指令
  （SCENARIO_CASE.md A4 的「查词典模式」风险在代码里硬解）；
④反馈实录收集：correction / teaching 与 WS 事件同源同序留存，课后经
  live_feedback() 导出进报告（live_ws 收口时取走）。

ScenarioNudger 是 D1 沉默分级探询的后端执行端（SCENARIO_CASE.md D1）：前端
沉默计时器分级发 nudge {stage} 控制消息（bridge 上行泵接线），这里查表注入
分级舞台指令 + 防抖。

仅情景对话接线（live_ws）；方式 A 考官不声明 tools 也不接 nudge，保持中立零破壁。
"""

import logging
import time
from contextlib import suppress

from app.live.director import send_stage_direction
from app.report import LiveCorrection, LiveFeedback, LiveTeaching
from app.scenario_cases import (
    CASES,
    GRAMMAR_AFTER_HELP_DIRECTIVE,
    GRAMMAR_SILENT_DIRECTIVE,
    GRAMMAR_SPEAK_DIRECTIVES,
    HELP_DIRECTIVES,
    HELP_OVERUSE_DIRECTIVE,
    NUDGE_DIRECTIVES,
)

logger = logging.getLogger(__name__)

HELP_STREAK_WINDOW_S = 90   # 距上次求助 < 此窗口算"连续"（否则计数重置）
HELP_OVERUSE_THRESHOLD = 3  # 连续第 N 次求助起，改发「鼓励先自己试」指令

_FALLBACK_KIND = "explicit_ask"   # 模型传了枚举外的 kind 时按显式求助应答

# —— grammar_note 口头规则（出现即提示，用户决策）：被压掉的仍发 correction 事件 —— #
GRAMMAR_SPEAK_GAP_S = 10        # 防同轮双发保险：模型违规一轮连调两次时压掉第二条
_SAME_TURN_WINDOW_S = 5.0       # 距上次 language_help < 此窗口视作同轮（批内连发）


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
        # grammar_note 控频状态（语法纠错与中文求助分开计）
        self._last_help_at: float | None = None       # 同轮重叠判定专用钟（review W1：
        self._last_help_kind: str | None = None       # 与 streak 钟分离，grammar 用后即耗）
        self._grammar_spoken_at: float | None = None  # 口头纠错防双发闸
        self._grammar_spoken_count = 0                # 口头纠错次数：模板轮换游标
        # 反馈实录（课后进报告 live_feedback 区）：与 WS 事件同源同序；
        # WS 已死事件发不出也照收——报告不应因前端断开丢素材。
        self._corrections: list[LiveCorrection] = []
        self._teachings: list[LiveTeaching] = []

    async def on_tool_call(self, name: str, args: dict) -> dict:
        """处理一次模型 tool 调用，返回 tool response 体（必须瞬时，无外呼）。

        按工具名路由：language_help（求助应答）/ grammar_note（纠错控频）。
        未知工具名（模型幻觉）返回错误体不抛——宁可模型收到 error 后自行圆场，
        也不让整条会话因一次幻觉调用崩掉。
        """
        if name == "language_help":
            return await self._on_language_help(args)
        if name == "grammar_note":
            return await self._on_grammar_note(args)
        logger.warning("help: 未知 tool 调用被拒：%s", name)
        return {"error": f"unknown tool: {name}"}

    async def _on_language_help(self, args: dict) -> dict:
        kind = args.get("kind")
        if kind not in HELP_DIRECTIVES:
            logger.warning("help: 枚举外 kind=%r，按 %s 应答", kind, _FALLBACK_KIND)
            kind = _FALLBACK_KIND
        english = args.get("english") or ""
        example = args.get("example") or ""
        self._last_help_at = self._clock()   # grammar 同轮重叠判定用（专用钟）
        self._last_help_kind = kind
        self._teachings.append(
            LiveTeaching(
                kind=kind, chinese=args.get("chinese") or "",
                english=english, example=example,
            )
        )
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

    async def _on_grammar_note(self, args: dict) -> dict:
        """grammar_note：检出（模型）与呈现（这里控频）分离（SCENARIO_CASE.md B1）。

        三态指令：①说——回答最前一句纠正（与中文求助同轮则放中文应答之后，
        用户决策的顺序规则）；②静默——同轮双发压掉 / mixed_cn 同轮 recast
        已覆盖。出现即提示（用户决策）：除上述两种静默外每轮必说一条。
        无论说不说，correction 事件都发前端（spoken 标记区分），数据不丢。
        """
        now = self._clock()
        original = args.get("original") or ""
        fixed = args.get("fixed") or ""
        note = (args.get("note") or "").strip().lower()
        # 同轮判定用专用钟且**用后即耗**（review W1）：跨轮的快速衔接不再被
        # 上一轮的 mixed_cn 误静默——一次 language_help 只配对一次 grammar_note
        same_turn_help = (
            self._last_help_at is not None
            and now - self._last_help_at < _SAME_TURN_WINDOW_S
        )
        self._last_help_at = None
        if same_turn_help and self._last_help_kind == "mixed_cn":
            # recast 重述时天然已纠正，再口头提一遍是啰嗦（确认的边际 #3）
            spoken, template = False, GRAMMAR_SILENT_DIRECTIVE
        elif (
            self._grammar_spoken_at is not None
            and now - self._grammar_spoken_at < GRAMMAR_SPEAK_GAP_S
        ):
            spoken, template = False, GRAMMAR_SILENT_DIRECTIVE   # 防同轮双发
        else:
            spoken = True
            self._grammar_spoken_at = now
            self._grammar_spoken_count += 1
            if same_turn_help:
                template = GRAMMAR_AFTER_HELP_DIRECTIVE   # 中文应答之后（单模板）
            else:
                # 回答最前：≥2 变体按口头次数轮换（防多次纠错句式重复）
                template = GRAMMAR_SPEAK_DIRECTIVES[
                    (self._grammar_spoken_count - 1) % len(GRAMMAR_SPEAK_DIRECTIVES)
                ]
        # 对照式填槽（say {fixed}, not {original}）：{scene} 先填（受控文本），
        # 模型产出的片段后填
        directive = (
            template.replace("{scene}", self._scene)
            .replace("{fixed}", fixed)
            .replace("{original}", original)
        )
        self._corrections.append(
            LiveCorrection(original=original, fixed=fixed, note=note, spoken=spoken)
        )
        with suppress(Exception):
            await self._ws.send_json(
                {
                    "type": "correction",
                    "case": self._case,
                    "original": original,
                    "fixed": fixed,
                    "note": note,
                    "spoken": spoken,
                }
            )
        return {"directive": directive}

    def live_feedback(self) -> LiveFeedback | None:
        """导出本场反馈实录（课后报告 live_feedback 区）；无任何事件返回 None。

        None 而非空结构：报告字段 null = 「无 live 反馈」，前端按 null 隐藏整区。
        """
        if not self._corrections and not self._teachings:
            return None
        return LiveFeedback(
            corrections=list(self._corrections), teachings=list(self._teachings)
        )


NUDGE_DEBOUNCE_S = 8   # 距上次 nudge < 此值忽略（防前端计时器 bug 连发轰炸模型）


class ScenarioNudger:
    """D1 沉默分级探询的后端执行端。状态只在事件循环线程被触碰（无锁）。

    阈值与分级判断全在前端（只有前端知道播放队列何时排空、麦克风有没有人声，
    与方式 A「前端播完收尾语音自动收束」同一判断归属）；后端只做①按 stage
    查表注入舞台指令 ②防抖。C5 口头暂停与 nudge 的互斥内置在指令文本里，
    由模型用对话上下文裁决。
    """

    def __init__(self, case: str, *, clock=time.monotonic):
        # 入口已按白名单守门（live_ws._parse_params），直查快败
        self._scene = CASES[case].scene_label
        self._clock = clock         # 可注入假钟（防抖测试确定性）
        self._last_at: float | None = None

    async def on_nudge(self, session, stage) -> None:
        """注入一条分级探询舞台指令；防抖窗口内的重复 nudge 忽略。

        stage 来自前端 JSON（不可信输入）：非整数按 1（最轻介入）处理，
        越界钳制到模板键域——任何取值都不该让会话崩。
        """
        now = self._clock()
        if self._last_at is not None and now - self._last_at < NUDGE_DEBOUNCE_S:
            logger.debug("nudge 防抖忽略：距上次 %.1fs", now - self._last_at)
            return
        self._last_at = now
        try:
            stage = int(stage)
        except (TypeError, ValueError):
            stage = 1
        stage = min(max(stage, min(NUDGE_DIRECTIVES)), max(NUDGE_DIRECTIVES))
        await send_stage_direction(
            session, NUDGE_DIRECTIVES[stage].replace("{scene}", self._scene)
        )
