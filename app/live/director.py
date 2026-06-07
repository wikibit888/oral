"""雅思方式 A 导演状态机（模型驱动 + 短语检测 + 延迟 UI + 分层安全网）。

设计依据成熟口语模拟产品的实测运行时行为（live 抓取实锤）。核心范式：
**考官（模型）当导演决定何时转场，后端只负责①检测宣告 ②延迟 UI 到宣告说完
③兜底防挂死**——不再数轮数（旧实现 _examiner_turns >= N 强转的两宗罪：转场
机械化、末问被吞）。

状态：p1 → p2_prep → p2_talk → p3 → done

转场如何发生（三条主边界）：
- P1→P2、P2→P3、P3→done 全由考官 persona 自然跑完该 part 后**自己说出**固定宣告句
  （"That is the end of Part 1." / "...more general questions..." / "That is the end
  of the speaking test."）。director 在 `on_examiner_transcript` 累积考官转写、子串
  匹配到宣告短语 → 置 `_pending`（**不立即动手**）。
- `_pending` 在该考官轮的 `turn_complete`（宣告说完整）才兑现转场——**语音必先于
  视觉**（参考实现同款 defer-until-spoken：等宣告轮 responseEnded 才动 UI）：
  P1 末考官说完"end of Part 1"才弹 cue card；备题倒计时再晚一拍——**念题轮说完**
  （"Your preparation time starts now."）才发 start_prep_timer / 起 60s 计时
  （实测反馈②：进 p2_prep 就起跳会边念题边扣秒）；P3 末说完收尾句才进 done。
  末问的回答天生在考官宣告轮之前由 Gemini VAD 自然收口，**不会被吞**。

开场防吞（实测反馈①）：网络慢时 ws.onopen 起积压的麦克风帧随 bridge 启动爆发涌入
Live，VAD 误判插话把开场轮 barge-in 掐掉。两层对策：① start() 即 input_paused 门控
麦克风（积压帧 + 开场期杂音全丢），开场轮真说完（首个有声 turn_complete）才放行；
② 开场看门狗——OPENING_NUDGE_S 秒无任何考官音频判开场指令被吞，重发（至多 3 次）。

长谈独白上限（IELTS_CASE §2 上限层）：p2_talk 入场起 MAX_MONOLOGUE_S 计时器——
邀请轮（首个有声轮）锚定保持，考官再次发声（软探询/追问）即撤；到点注入切断指令
让考官礼貌 "Thank you" 收口 + 问追问，不转场、不硬切音频流。与 MAX_P2_TALK_S
整段安全网并存：前者切独白，后者兜整段死锁。

收官（实测反馈④）：进 done 即重新 input_paused（参考实现的 "scoring mode: user
speech ignored"——考后杂音不进 Live 不进切片）；自动结束由前端完成：收到
part_change done 且收尾语音**播完**后自动走 end_session 流程（只有前端知道播放
队列何时排空，后端在 turn_complete 时收尾音频还在客户端缓冲里）。

为何短语检测在这里是对的（旧方案曾否决，实测推翻）：考官 persona 被要求逐字说出
宣告句，配 ①延迟到 turn 边界 ②每段超时兜底（_arm_fallback 力转），脆弱性被消除。

防挂死安全网（非主推力）：每段进入即武装一个超时计时器，考官迟迟不说宣告句就
**强制转场**（force_*，幂等查 state）。遵守 _end_prep 的防自取消铁律（review W1）。
已知洞（可接受）：force_* 注入兜底提示后种 `_pending`，靠下一个**真发声轮**的
turn_complete 兑现——若 Live 在 force 后彻底静默（无音频轮），`_pending` 永挂、
不再二次救援；但 Live 全静默时 WS 自身也会超时断连，live_ws.py finally 调
cancel_timers 收尾、会话留 processing 待人工处理，故不补会话级二层兜底。

接线（bridge）：
- 下行泵：考官音频帧 → on_model_audio；考官转写 → on_examiner_transcript（短语检测）；
  turn_complete → on_turn_complete（兑现 _pending）；interrupted → on_interrupted。
- 上行泵：音频帧前查 input_paused（备题丢帧）；ready 控制 → on_ready。
"""

import asyncio
import logging
import random
from collections.abc import Callable

from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

# 考官音色注册表：voice_id（Live 半级联可选音色）→ 考官自报姓名。每场开考由
# pick_examiner_voice 随机抽一个，音色与名字同源派生（不会女声自称 Puck）；
# 这些音色 ID 本就是人名，默认同名——想换称呼只改右值（如 "Kore": "Ms. Kore"）。
EXAMINER_VOICES = {
    "Puck": "Puck", "Charon": "Charon", "Kore": "Kore", "Fenrir": "Fenrir",
    "Aoede": "Aoede", "Leda": "Leda", "Orus": "Orus", "Zephyr": "Zephyr",
}


def pick_examiner_voice() -> str:
    """每场随机抽一个考官音色；settings.live_voice 非空则固定用它（pin 优先）。"""
    if settings.live_voice:
        return settings.live_voice
    return random.choice(sorted(EXAMINER_VOICES))

# 中立考官 persona —— 同时是整场考试的**剧本**：考官自己驱动三个 part，并在每段
# 结束逐字说出固定宣告句（director 据此检测转场）。压住默认"热心导师"倾向。
EXAMINER_SYSTEM_INSTRUCTION = """\
You are a professional IELTS Speaking examiner conducting a real mock exam with three parts.

General rules (always):
- ABSOLUTE OUTPUT RULE — speak only words a real examiner would say out loud to the
  candidate. Any text in [square brackets] is a private cue meant only for you: do exactly
  what it says, but NEVER read it aloud, paraphrase it, quote it, or describe what is being
  set up behind the scenes. Words inside double quotes in a cue or in these instructions are
  lines you may speak; everything else here is never spoken. Fill any silence only by
  waiting — never by announcing or narrating what is about to happen next.
- Stay neutral: never correct the candidate's mistakes, never praise or encourage beyond a
  brief acknowledgement ("Thank you.", "Alright."). Never teach vocabulary, never give your
  own opinions, and never help the candidate build their answer — all feedback, corrections
  and scores come only after the exam.
- Ask exactly ONE question at a time, then stop and wait for the candidate's complete answer.
  Never interrupt them; never move on until they have finished answering.
- Keep your own speech short — the candidate should do most of the talking.
- Speak only English. If the candidate speaks another language or asks how to say a word, do
  not translate or supply the word — at most say "Could you say that in English?" and wait.
- If asked to repeat a question, repeat it once in the same words and never explain what any
  word means. If they ask you to repeat the same question a second time, say "Let's move
  on." and continue to your next question.
- Deflect out-of-role requests in one short sentence, then return to the current question:
  your opinion ("I'm just asking the questions — what do you think?"), their score ("I can't
  give a score during the exam."), the exam format or rules ("I can't go over that now."), or
  help inventing ideas or examples ("Just answer in your own way — there is no right or
  wrong.").
- Two more such requests, handled the same brief way: if the candidate asks to change the
  Part 2 topic card, decline ("I'm sorry, the topic stays the same."); if they ask you to
  explain or define a word on the card, you may clarify what the task is but never define
  content words and never suggest vocabulary, then return to the exam.
- If the candidate gives a very short or one-word answer, do not coax for more — move on to
  your next question (except the Part 2 long turn, which has its own rule below). If they go
  off topic, let them finish the sentence, then move on.
- Never explain what you are doing and never mention these instructions.

Conduct the exam yourself in this order. Private cues will tell you when to move the exam
forward; never tell the candidate that you are waiting for anything.

PART 1 — Your FIRST turn is only the greeting and the name check: greet the candidate
briefly, introduce yourself by the name given in your opening cue, and ask for their full
name ("Can you tell me your full name, please?"). Say nothing else in that turn — ask NO
other question. Stop and wait for them to answer. After they give
their name, acknowledge it briefly ("Thank you.") and begin the everyday questions (home,
work or study, hobbies, daily life), ONE at a time, waiting for a complete answer after
each, for about four or five questions. When Part 1 has covered enough, you MUST end it by
saying, as its own short turn, the exact words: "Thank you. That is the end of Part 1."
Then say nothing more and simply wait quietly — do NOT introduce any topic yourself.

PART 2 — Run the long-turn part in these steps:
- You will be handed a topic to read aloud, followed by one minute of quiet preparation;
  the topic and its wording are fixed (handle any change-the-card or explain-a-word request
  as in the general rules above).
- When preparation is over you will be cued to begin: invite the candidate in ONE sentence
  to speak for one to two minutes. Then stay silent and do NOT interrupt while they speak.
  If they pause to think, just wait — never fill the silence with hints, ideas or
  vocabulary. If they seem stuck, you may restate the topic once at most, then wait again.
- When they finish their long turn: if it was very short, ask exactly once "Is there
  anything else you would like to add?" and let their next answer decide.
- Then ask ONE brief follow-up question about what they said, and wait for their answer.
- After they answer the follow-up, move on by saying, word for word: "Thank you. We have
  been talking about this topic. I would now like to discuss some more general questions
  related to it." Then immediately ask your first Part 3 question.

PART 3 — Discuss more abstract questions related to the Part 2 topic (society, trends,
opinions), ONE at a time, for about four or five questions. When Part 3 has covered enough,
you MUST end the exam by saying, as its own short turn, the exact words: "Thank you. That is
the end of the speaking test." Then STOP and say nothing further.

Never announce a Part transition early, and never close the exam on your own initiative —
only at the points above, and only after the candidate has finished their current answer.\
"""

PREP_SECONDS = 60          # P2 备题时长（官方 1 分钟）
# P2 长谈独白上限（IELTS_CASE §2 上限层，D1 决策 a）：官方 2 分钟 + 邀请/起话余量。
# 自长谈邀请注入起算（natural 模式麦克风帧连续流式，无法精确测"开口"时刻），到点注入
# 切断指令让考官礼貌收口 + 问追问——仍有语音宣告，不硬切音频流；考官在邀请轮之后
# 再次发声（探询/追问）即视为独白自然结束，计时器撤销。
MAX_MONOLOGUE_S = 130
OPENING_NUDGE_S = 10       # 开场看门狗：迟迟无考官音频 → 重发开场指令（指令被吞/丢包）
_OPENING_NUDGE_TRIES = 3   # 看门狗至多重发次数（再不行交给 MAX_P1_S 安全网）
MAX_CUE_READ_S = 45        # 念题轮兜底：cue 轮迟迟不 turn_complete → 倒计时照样起跳
# 各段防挂死超时（安全网，非主推力；量级参照参考实现的分段阈值：
# part1 240s / part2_speaking 150s+followup / part3 300s，留足不切断正常考试）
MAX_P1_S = 300             # Part 1 内考官迟迟不说"end of Part 1"→强转备题
MAX_P2_TALK_S = 210        # 长谈+追问+转 P3 上限（邀请后考官不收口→强转 P3）
MAX_P3_S = 300             # Part 3 内考官迟迟不说收尾句→强制收官

# 转场宣告短语（小写子串匹配考官转写；persona 被要求逐字说出）。务必用**带语境的
# 长子串**，不用裸词——P1/P3 是特定考试套语误匹配极低；P2→P3 的 "general question"
# 等裸词可能出现在考官的普通追问里（review W2），故只收带语境组合。实测反馈③：
# 模型常换说法（"Let's move on to Part 3" / "We've been talking about..."），三条
# 短语漏检卡死 p2——拓宽变体；"part 3"/"been talking about" 这类较泛的锚配
# on_examiner_transcript 的状态门（P2→P3 只在 p2_* 态认）防 P1 开场闲聊误跳。
_P1_END_PHRASES = ("end of part 1", "end of part one", "end of the first part")
_P2_TO_P3_PHRASES = (
    "more general question", "general questions related", "discuss some more general",
    # 剧本引导句（带 we 前缀防撞追问开场白 "You've been talking about..."，review W2）
    "we have been talking about", "we've been talking about",
    "part 3", "part three",          # 模型自报转场 "let's move on to Part 3"
)
_CLOSING_PHRASES = (
    "end of the speaking test", "end of your speaking test", "end of the exam",
    "end of the test", "end of this test",
    "end of part 3", "end of part three",       # 收尾变体（优先级先于 P2→P3 检测）
    "concludes the speaking test", "speaking test is over",
)


# 状态单调序：转场只前进不后退；任一目标只进入一次（主推力 / 安全网谁先到谁生效，
# 另一路被序号守卫挡掉，等价于旧的 `state != X` 幂等查重，但支持跳段前进）。
_STATE_ORDER = {"p1": 0, "p2_prep": 1, "p2_talk": 2, "p3": 3, "done": 4}


def _matches(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


async def send_stage_direction(session, prompt: str) -> None:
    """注入方括号舞台指令：作为文本回合发给 Live，演员照做但不读出。

    方式 A 考官与情景角色共用（persona 内置同一条方括号规则）——情景开场指令
    （live_ws._pick_opener）也走这里。
    """
    await session.send_client_content(
        turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
        turn_complete=True,
    )


# —— 导演提示（方括号 = 考官不读出）—— #
# 开场（实测 bug①）：本轮只 greet+自报姓名+问名一件事——旧版把"问名+首个 P1 问"塞
# 同一条指令，模型一口气连发、候选人没机会答名字。首个内容问改由答名后考官按
# persona 自续。{name} = 本场考官名（IeltsDirector(examiner_name=...)，由
# live_ws 从本场随机抽中的音色经 EXAMINER_VOICES 派生——音色与名字同源）。
_OPENING_TEMPLATE = (
    "[Stage direction: Begin the exam now. Start Part 1, but this turn only: greet the "
    "candidate in one short sentence, introduce yourself as \"{name}\", and ask for their "
    "full name. Do NOT ask any other question yet and do NOT introduce a topic. After you "
    "ask their name, stop and wait for their reply.]"
)
# 开场看门狗重发专用（幂等版）：慢首包（>OPENING_NUDGE_S 才出声）时重发完整开场会
# 二次问候——nudge 文本自带"已问候则不再问候"分支。
_OPENING_NUDGE_TEMPLATE = (
    "[Stage direction: If you have not yet spoken, begin now: greet the candidate in one "
    "short sentence, introduce yourself as \"{name}\", and ask for their full name, then "
    "stop and wait. If you have already greeted them, do not greet again — simply continue.]"
)
# 进备题（P1 宣告说完后注入）：纯祈使"你要说的话"清单（实测 bug②：旧版含 "they are
# shown on the candidate's card" 等可念解说，模型把指令当台词读出）——引号内是台词、
# 引号外永不出口；考官不自拟题。
_P2_CUE_TEMPLATE = (
    "[Stage direction: Say exactly these words to the candidate, in order, and add nothing "
    "else: first \"Now, here is your topic.\" then read this line aloud word for word: "
    "\"{topic}\" then \"You have one minute to prepare. Your preparation time starts now.\" "
    "After that say nothing at all and wait. Speak only the words in quotes — do not say "
    "anything about a card, about preparation, or about what you are doing.]"
)
# 备题结束→唤醒考官请长谈（追问 + 转 P3 宣告均预埋在 persona，考官照剧本走）
_P2_TALK_PROMPT = (
    "[Stage direction: Preparation time is over. In one short sentence invite the candidate "
    "to begin their long turn now, then stay silent and do not interrupt while they speak.]"
)
# 长谈独白满 2 分钟（MAX_MONOLOGUE_S 到点）：让考官礼貌切断 + 问追问（IELTS_CASE §2
# 上限层）。纯动作指令——不含"已说满两分钟"类时间断言（解说式状态描述是泄漏素材，
# 模型会照念"you have spoken for two minutes"，违反「不主动播报时间」）。
_P2_CUT_MONOLOGUE_PROMPT = (
    "[Stage direction: Bring the long turn to a close now. At the next natural pause, "
    "politely cut in: say \"Thank you.\" and ask ONE brief follow-up question about what "
    "they said. Do not mention time or timing.]"
)
# —— 安全网兜底提示（考官迟迟不说宣告句时强制推进，参考实现同款 fallback prompt）——
# 同为纯动作指令：旧版 "Part 1 has run long enough" 等旁白是可念解说，已删。 —— #
_P1_FORCE_PROMPT = (
    "[Stage direction: At the next natural pause, end Part 1 now by saying \"Thank you. "
    "That is the end of Part 1.\" and then stop.]"
)
_P2_TO_P3_FORCE_PROMPT = (
    "[Stage direction: Move on now: say \"Thank you. I would now like to discuss some more "
    "general questions related to it.\" then ask your first Part 3 question.]"
)
_CLOSING_FORCE_PROMPT = (
    "[Stage direction: End the exam now by saying \"Thank you. That is the end of the "
    "speaking test.\" and then stop. Do not ask any more questions.]"
)


class IeltsDirector:
    """单次方式 A 会话的状态机。状态推进只发生在事件循环线程（无锁）。

    states: p1 → p2_prep → p2_talk → p3 → done

    推进时钟：考官真发声轮的 turn_complete 兑现 `_pending`（短语检测在前一刻种下）。
    `_pending` 来源二选一：①考官说出宣告短语（主，on_examiner_transcript 检测）；
    ②该段超时安全网到点 force_*（兜底，直接转，幂等）。两者经 _set_state 互斥。
    """

    def __init__(self, cue_card: dict, examiner_name: str = "Puck"):
        self._card = cue_card
        self._examiner_name = examiner_name   # 本场考官自报姓名（与音色同源）
        self.state = "p1"
        self.input_paused = False
        self._turn_had_audio = False      # 本轮考官是否真发过声（空轮不推进）
        self._turn_transcript = ""        # 本考官轮累积转写（小写，供短语检测）
        self._pending: Callable | None = None   # 待 turn_complete 兑现的转场动作
        self._opening_gate = False        # 开场门控：开场轮说完前麦克风帧全丢（反馈①）
        self._heard_examiner = False      # 是否听到过任何考官音频（开场看门狗判据）
        self._prep_pending = False        # 念题轮说完才起跳倒计时（反馈②）
        self._ready_early = False         # 念题期抢按 ready：记下，念完直接进长谈
        self._p2_invite_seen = False      # p2_talk 首个有声轮 = 长谈邀请（独白计时器锚点）
        self._opening_task: asyncio.Task | None = None    # 开场看门狗
        self._prep_task: asyncio.Task | None = None       # P2 备题 60s 计时器
        self._monologue_task: asyncio.Task | None = None  # P2 独白 2 分钟上限（D1）
        self._fallback_task: asyncio.Task | None = None   # 当前段防挂死安全网

    # —— bridge 同步钩子（无 await）—— #

    def on_model_audio(self) -> None:
        """考官音频帧到达：标记本轮真说了话。

        Live 偶发**无音频的 turn_complete**（导演文本指令的回执轮）——只有真出过
        声的轮才推进状态机，否则 FSM 抢跑、指令堆进未完成生成流卡死。
        `_heard_examiner` 一次性置位：开场看门狗据此判开场指令是否被吞。
        """
        self._turn_had_audio = True
        self._heard_examiner = True

    def on_examiner_transcript(self, text: str) -> None:
        """考官转写增量到达：累积本轮转写并做转场短语检测（主推力）。

        检测命中只**种下** `_pending`（同步无 await，不能在此转场）；真正转场延迟到
        本轮 `turn_complete`——保证考官把宣告句说完整、语音先于视觉。已种下不重种。

        **全状态检测 + 优先级 + 单调前进**（实测实锤：模型不严格遵守每段剧本，会压缩
        P2/P3、直接滑进 P3 并说收尾而不报 P2→P3 宣告——若按预期 state 门控，收尾会在
        p2_talk 漏检、FSM 卡死）。故：收尾句（终态）在任何活动态都认；优先级
        收尾 > P2→P3 > P1末，且只认能前进的目标（_can_advance）。
        例外：P2→P3 只在 p2_* 态认（短语已拓宽到 "part 3" 等较泛锚，反馈③）——
        开场闲聊提到 "Part 3"（讲解考试结构）绝不能 p1 直跳 p3 把 cue card 整段跳掉；
        cue card 是系统派发的，不归模型驱动。开场轮（门控未放行）整轮不检测：
        开场是问候+问名，任何"宣告"只可能是讲解考试结构的误匹配（"after the end
        of Part 1 you will..."），种下会在开场轮 turn_complete 即跳段（review W1）。
        """
        if not text or self._pending is not None or self._opening_gate:
            return
        self._turn_transcript += text.lower()
        t = self._turn_transcript
        if self._can_advance("done") and _matches(t, _CLOSING_PHRASES):
            self._pending = self._enter_done
        elif self.state in ("p2_prep", "p2_talk") and _matches(t, _P2_TO_P3_PHRASES):
            self._pending = self._enter_p3
        elif self._can_advance("p2_prep") and _matches(t, _P1_END_PHRASES):
            self._pending = self._enter_p2_prep

    def _can_advance(self, target: str) -> bool:
        """目标状态序号严格大于当前——单调前进 + 幂等（已到/越过则不再转）。"""
        return _STATE_ORDER[self.state] < _STATE_ORDER[target]

    def on_interrupted(self) -> None:
        """考官被打断：清发声标记 + 本轮转写 + 未兑现的 _pending。

        被打断的宣告轮（宣告没说完整）绝不能转场——清掉重新检测；残留发声标记
        会让下一个空回执轮被误计（review C1）。
        """
        self._turn_had_audio = False
        self._turn_transcript = ""
        self._pending = None

    # —— 生命周期 —— #

    async def start(self, websocket, session) -> None:
        """建链后调用：门控麦克风、宣布 P1、让考官开场、武装看门狗 + P1 安全网。

        开场门控（反馈①）：start 在 bridge 之前跑——input_paused 先于上行泵首帧
        置位，建链期积压的麦克风帧 + 开场期杂音整段丢弃，不进 Live、不触发 VAD
        barge-in，开场轮不可能被吞。开场轮真说完（首个有声 turn_complete）放行。
        """
        self.input_paused = True
        self._opening_gate = True
        await websocket.send_json({"type": "part_change", "part": "p1"})
        await self._direct(
            session, _OPENING_TEMPLATE.format(name=self._examiner_name)
        )
        self._opening_task = asyncio.create_task(self._opening_watchdog(session))
        self._arm_fallback(MAX_P1_S, self._force_enter_p2_prep, websocket, session)

    async def _opening_watchdog(self, session) -> None:
        """开场看门狗（反馈①另一半）：开场指令本身可能在慢网/抖动中被吞——
        OPENING_NUDGE_S 秒无任何考官音频就补发 nudge，至多 _OPENING_NUDGE_TRIES 次，
        再不行交给 MAX_P1_S 安全网。首帧音频到达后由 on_turn_complete 撤销。
        补发用幂等 nudge 文本而非原开场指令：慢首包（生成未丢、只是 >10s 才出声）下
        重发完整开场会让考官二次问候，nudge 自带"已问候则不再问候"分支。
        """
        for _ in range(_OPENING_NUDGE_TRIES):
            await asyncio.sleep(OPENING_NUDGE_S)
            if self._heard_examiner:
                return
            logger.warning(
                "director: 开场 %ss 无考官音频，补发开场 nudge", OPENING_NUDGE_S
            )
            await self._direct(
                session, _OPENING_NUDGE_TEMPLATE.format(name=self._examiner_name)
            )

    async def on_turn_complete(self, websocket, session) -> None:
        """考官说完一轮——兑现本轮种下的转场（defer-until-spoken）。

        空轮（无任何考官音频）不兑现：见 on_model_audio。非转场轮（考官只是问了
        一个问题）什么都不做——用户随后自然作答，Gemini VAD 收口，模型继续驱动。
        开场门控在首个**有声**轮放行（空回执轮不算——开场还没真说）；备题倒计时
        在 _pending 之后查：转场（含跳段收官）优先于起跳，_set_state 会清掉它。
        """
        if not self._turn_had_audio:
            logger.info("director: 空 turn_complete（无考官音频），不兑现")
            return
        self._turn_had_audio = False
        self._turn_transcript = ""        # 本轮转写用完即弃，下一轮重新累积
        # P2 独白计时器锚定/撤销：p2_talk 首个有声轮 = 长谈邀请（计时器保持武装）；
        # 此后考官再次发声（软探询/追问）= 独白已自然结束，2 分钟切断失去意义即撤。
        # 被打断的邀请轮（空轮）不锚定——极端下计时器可能在追问期才到点，注入的
        # 切断指令让考官多说一句 Thank you + 追问，有界且无状态破坏。
        if self.state == "p2_talk" and self._monologue_task is not None:
            if not self._p2_invite_seen:
                self._p2_invite_seen = True
            else:
                self._cancel_monologue()
        if self._opening_gate:
            self._opening_gate = False
            self.input_paused = False
            if self._opening_task is not None:
                self._opening_task.cancel()
                self._opening_task = None
        if self._pending is not None:
            action, self._pending = self._pending, None
            await action(websocket, session)
        elif self._prep_pending:
            await self._start_prep_countdown(websocket, session)

    async def on_ready(self, websocket, session) -> None:
        """前端「我准备好了」：提前结束备题（与 60s 计时器先到先得）。

        念题期抢按（倒计时还没起跳）只记 `_ready_early`，不能立即转——此刻注入
        长谈邀请会跟未完成的念题生成流绞在一起（1008 风险），念题轮说完直接进长谈。
        """
        if self._prep_pending:
            self._ready_early = True
            return
        await self._end_prep(websocket, session)

    def cancel_timers(self) -> None:
        """会话收束时调：取消未触发的看门狗 / 备题 / 独白 / 安全网计时器，不留孤儿任务。"""
        if self._opening_task is not None:
            self._opening_task.cancel()
            self._opening_task = None
        if self._prep_task is not None:
            self._prep_task.cancel()
            self._prep_task = None
        if self._monologue_task is not None:
            self._monologue_task.cancel()
            self._monologue_task = None
        if self._fallback_task is not None:
            self._fallback_task.cancel()
            self._fallback_task = None

    # —— 转场动作（幂等：先查 state；主/兜底两路谁先到谁生效）—— #

    async def _enter_p2_prep(self, websocket, session) -> None:
        """P1 宣告说完 → 进备题。考官已说完"end of Part 1"，此刻才念题 + 弹 cue card。

        先停输入再走 await 链（review S2）：备题嘀咕不算样本，闸门关在真正进备题
        前一刻；末问回答此前已由 Gemini VAD 自然收口，不丢帧。cue card 晚于 P1
        收尾宣告语音到前端——语音先于视觉；卡随念题同屏（persona 不念 bullets，
        "they are shown on the candidate's card"）。
        倒计时再延一拍（反馈②）：此处只种 `_prep_pending`，念题轮真说完
        （"Your preparation time starts now." 的 turn_complete）才起跳——
        MAX_CUE_READ_S 兜底防念题轮丢失卡死备题。
        """
        if not self._can_advance("p2_prep"):
            return
        self.input_paused = True
        await self._set_state(websocket, "p2_prep")
        await self._direct(session, _P2_CUE_TEMPLATE.format(topic=self._card["text"]))
        await websocket.send_json(
            {
                "type": "present_cue_card",
                "card": {
                    "id": self._card["id"],
                    "text": self._card["text"],
                    "bullets": self._card.get("bullets") or [],
                },
            }
        )
        self._prep_pending = True
        self._arm_fallback(
            MAX_CUE_READ_S, self._start_prep_countdown, websocket, session
        )

    async def _start_prep_countdown(self, websocket, session) -> None:
        """念题轮说完（或 MAX_CUE_READ_S 兜底到点）→ 倒计时此刻才起跳（反馈②）。

        幂等：主推力（turn_complete）与兜底（安全网 task）谁先到谁生效，后到者被
        `_prep_pending` 挡掉。念题期抢按过 ready 的直接进长谈，不再走 60s。
        """
        if self.state != "p2_prep" or not self._prep_pending:
            return
        self._prep_pending = False
        self._cancel_fallback()           # 念题兜底已无用（防自取消铁律内置）
        if self._ready_early:
            self._ready_early = False
            await self._end_prep(websocket, session)
            return
        await websocket.send_json({"type": "start_prep_timer", "seconds": PREP_SECONDS})
        self._prep_task = asyncio.create_task(self._prep_timeout(websocket, session))

    async def _force_enter_p2_prep(self, websocket, session) -> None:
        """P1 安全网到点：考官没说宣告句——先逼它说，再进备题。

        注入兜底提示让考官补一句"end of Part 1"（仍有语音宣告，不退化成静默硬切），
        随后种 _pending，被逼出的宣告轮 turn_complete 兑现进备题。
        """
        if not self._can_advance("p2_prep"):
            return
        await self._direct(session, _P1_FORCE_PROMPT)
        self._pending = self._enter_p2_prep

    async def _prep_timeout(self, websocket, session) -> None:
        await asyncio.sleep(PREP_SECONDS)
        await self._end_prep(websocket, session)

    async def _end_prep(self, websocket, session) -> None:
        """计时到点 / ready 提前——只有仍在 p2_prep 才转场（查重防双触发）。

        ⚠️ 绝不能 cancel 当前任务自己：计时器路径里 `_end_prep` 就跑在 `_prep_task`
        上，自取消的 CancelledError 会在随后 `_direct` 的网络 await 点注入，把发往
        Live 的指令帧截断在半截——服务端 1007/1008 杀连接（review W1）。ready 路径
        才真取消计时器。进长谈即武装 P2 安全网。
        """
        if self.state != "p2_prep":
            return
        self.input_paused = False
        task, self._prep_task = self._prep_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        await self._set_state(websocket, "p2_talk")
        await self._direct(session, _P2_TALK_PROMPT)
        # 独白 2 分钟上限（IELTS_CASE §2 上限层）：自邀请注入起算；锚定/撤销见
        # on_turn_complete。与 210s 整段安全网并存：130s 切独白 / 210s 兜整段死锁。
        self._p2_invite_seen = False
        self._monologue_task = asyncio.create_task(self._monologue_timeout(session))
        self._arm_fallback(MAX_P2_TALK_S, self._force_enter_p3, websocket, session)

    async def _monologue_timeout(self, session) -> None:
        """独白上限到点：考官仍未收口 → 注入切断指令（礼貌 Thank you + 一个追问）。

        只注入、不转场——后续 P2→P3 仍走考官宣告句的主推力；幂等查 state。
        """
        await asyncio.sleep(MAX_MONOLOGUE_S)
        if self.state != "p2_talk":
            return
        logger.info("director: P2 独白满 %ss，注入切断指令", MAX_MONOLOGUE_S)
        await self._direct(session, _P2_CUT_MONOLOGUE_PROMPT)

    def _cancel_monologue(self) -> None:
        """撤销独白计时器。_monologue_timeout 只注入指令、从不调 _set_state /
        _cancel_monologue，故无 _cancel_fallback 那种自取消路径；current_task 守卫
        纯为与其它计时器槽位写法统一的防御惯例（review W2 注记）。"""
        task, self._monologue_task = self._monologue_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _enter_p3(self, websocket, session) -> None:
        """P2→P3 宣告说完 → 进 P3（考官已在同轮问出首个 P3 问）。武装 P3 安全网。

        允许从 p2_prep 跳进（模型偶尔不走完备题直接转）：跳段前先归还输入 + 撤备题计时器。
        """
        if not self._can_advance("p3"):
            return
        self._clear_prep()
        await self._set_state(websocket, "p3")
        self._arm_fallback(MAX_P3_S, self._force_enter_done, websocket, session)

    async def _force_enter_p3(self, websocket, session) -> None:
        """P2 安全网到点：逼考官说转场句 + 问首个 P3 问，再种 _pending 进 P3。"""
        if not self._can_advance("p3"):
            return
        await self._direct(session, _P2_TO_P3_FORCE_PROMPT)
        self._pending = self._enter_p3

    async def _enter_done(self, websocket, session) -> None:
        """收尾宣告说完 → 收官。考官说"end of the speaking test"即收——**从任何活动态**
        都可直达（实测：模型会在 p2_talk 直接说收尾、跳过 P3 宣告）。跳段前清备题。

        进 done 即重新停输入（反馈④，参考实现的 "scoring mode: user speech
        ignored"）：考后嘀咕不进 Live 不进切片，也不会再触发考官新轮。自动收束由
        前端完成——收到 part_change done 且收尾语音播完即自动走 end_session。
        """
        if not self._can_advance("done"):
            return
        self._clear_prep()
        self.input_paused = True
        await self._set_state(websocket, "done")

    async def _force_enter_done(self, websocket, session) -> None:
        """P3 安全网到点：逼考官补收尾句，再种 _pending 收官（仍有语音宣告）。"""
        if not self._can_advance("done"):
            return
        await self._direct(session, _CLOSING_FORCE_PROMPT)
        self._pending = self._enter_done

    def _clear_prep(self) -> None:
        """跳段前进时若仍在备题：归还输入 + 撤备题计时器（防自取消铁律 review W1）。
        非备题态调用是无副作用 no-op。
        """
        self.input_paused = False
        task, self._prep_task = self._prep_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    # —— 安全网计时器（与 _prep_task 独立槽位）—— #

    def _arm_fallback(self, seconds, action, websocket, session) -> None:
        """武装当前段防挂死安全网：到点执行 action（action 自带查 state 幂等）。"""
        self._cancel_fallback()
        self._fallback_task = asyncio.create_task(
            self._run_fallback(seconds, action, websocket, session)
        )

    async def _run_fallback(self, seconds, action, websocket, session) -> None:
        await asyncio.sleep(seconds)
        await action(websocket, session)

    def _cancel_fallback(self) -> None:
        """取消当前段安全网——同 _end_prep 防自取消铁律（review W1）：force_* 经
        _set_state 走到这里时正跑在 _fallback_task 自己身上，自取消会截断后续帧。
        """
        task, self._fallback_task = self._fallback_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _set_state(self, websocket, state: str) -> None:
        """统一转场：清 _pending / 备题待起跳标记 + 取消当前段安全网——旧段遗产
        绝不跨段生效（跳段进 p3/done 时残留的 _prep_pending 会在下一轮误起倒计时）。

        清理全在首个 await 之前同步完成：主推力（turn_complete 兑现）与兜底（安全网
        task）谁先动手，谁在让出控制权前就灭掉对方，无双转场窗口。
        """
        self.state = state
        self._pending = None
        self._prep_pending = False
        self._ready_early = False
        self._cancel_monologue()          # 离开 p2_talk 即撤独白上限（进入时机在 _end_prep）
        self._cancel_fallback()
        await websocket.send_json({"type": "part_change", "part": state})
        logger.info("director: 转场 → %s", state)

    @staticmethod
    async def _direct(session, prompt: str) -> None:
        """注入导演提示（薄别名：实现见模块级 send_stage_direction）。"""
        await send_stage_direction(session, prompt)
