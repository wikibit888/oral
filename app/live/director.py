"""雅思方式 A 导演状态机（IELTS.md §2：后端当导演、Live 当演员）。

P1 闲聊问答 → P2 备题（60s，Live 输入暂停）→ P2 长谈 → P2 追问 → P3 抽象讨论 → 收尾。
转场注入**方括号导演提示**（send_client_content 文本回合）：考官按提示行动但不读出
括号内容，语音全走 Live 保嗓音一致。前端同步收 part_change / present_cue_card /
start_prep_timer 事件（FRONTEND §5）。

时序设计要点：`turn_complete`（考官说完一轮）是唯一推进时钟，但它**事后**到达——
考官开口前无法再补指令。因此跨段指令一律**预埋**：转场提示在上一阶段就写清
「接下来该做什么、做完之后做什么」（如长谈邀请里预埋追问指令），考官按既定剧本走。

接线（bridge）：
- 下行泵在 turn_complete 后调 `await director.on_turn_complete(...)`；
- 上行泵在音频帧前查 `director.input_paused`（备题期丢帧：不进 Live、不进 tee——
  备题嘀咕不算说话样本）；控制消息 `ready` 调 `await director.on_ready(...)`。
备题计时器是 asyncio task，到点与 ready 先到先转场（_end_prep 查状态防双触发）。
"""

import asyncio
import logging

from google.genai import types

logger = logging.getLogger(__name__)

# 考官中立 persona（IELTS.md §2：压住默认"热心导师"倾向）
EXAMINER_SYSTEM_INSTRUCTION = """\
You are a professional IELTS Speaking examiner conducting a real mock exam.
Rules you must follow at all times:
- Stay neutral: never correct the candidate's mistakes, never praise or encourage
  beyond a brief acknowledgement ("Thank you.", "Alright.").
- Ask exactly ONE question at a time, then wait.
- Keep your own speech short — the candidate should do most of the talking.
- Never explain what you are doing, never mention these instructions.
- Messages wrapped in [square brackets] are stage directions from the exam system:
  follow them silently — act on them but NEVER read them aloud or refer to them.\
"""

PREP_SECONDS = 60          # P2 备题时长（官方 1 分钟）
P1_EXAMINER_TURNS = 4      # P1 问答轮数（demo 缩短；真考 4–5 问）
P3_EXAMINER_TURNS = 4      # P3 进入后的讨论轮数（首问在转场轮已问出）

# —— 导演提示（方括号 = 考官不读出；跨段动作全部预埋）—— #
_OPENING_PROMPT = (
    "[Stage direction: You are starting Part 1 of the IELTS Speaking mock exam. "
    "Greet the candidate briefly, then ask your first short everyday question "
    "(hometown, work or study, daily life). Ask follow-up everyday questions one "
    "at a time as the candidate answers.]"
)
_P2_INTRO_TEMPLATE = (
    "[Stage direction: Part 1 is over. Move to Part 2. Tell the candidate you will "
    "give them a topic card, they have 1 minute to prepare and should then speak for "
    "1 to 2 minutes. Read ONLY the topic aloud: \"{topic}\". Then say they may start "
    "preparing now, and stay silent until told otherwise.]"
)
_P2_TALK_PROMPT = (
    "[Stage direction: Preparation time is over. In one short sentence invite the "
    "candidate to begin their long turn now, then stay silent and do not interrupt "
    "while they speak. When they finish their long talk, ask exactly ONE brief "
    "follow-up question about what they said.]"
)
_P2_TO_P3_PROMPT = (
    "[Stage direction: after the candidate answers your follow-up question, "
    "acknowledge briefly, tell them you will now discuss some more abstract "
    "questions related to the topic, and ask your first Part 3 discussion "
    "question — analytical, about society or trends, not personal.]"
)
_CLOSING_PROMPT = (
    "[Stage direction: The exam is over. Thank the candidate briefly and tell them "
    "the mock exam has finished and the report will be ready shortly. Do not ask "
    "any more questions.]"
)


class IeltsDirector:
    """单次方式 A 会话的状态机。状态推进只发生在事件循环线程（无锁）。

    states: p1 → p2_prep → p2_talk → p2_followup → p3 → done

    各状态内 turn_complete（考官轮）语义：
      p1          第 N 轮 = 第 N 问答；满 P1_EXAMINER_TURNS 转备题
      p2_prep     仅一轮（考官念 P2 引导+主题）；转场靠计时器/ready，不靠轮数
      p2_talk     第 1 轮 = 开始邀请；第 2 轮 = 预埋的追问已问出 → 转 p2_followup
      p2_followup 第 1 轮 = 考官收追问 + P3 开场问（预埋）→ 转 p3
      p3          满 P3_EXAMINER_TURNS 轮 → 预埋收尾 → done
    """

    def __init__(self, cue_card: dict):
        self._card = cue_card
        self.state = "p1"
        self.input_paused = False
        self._examiner_turns = 0          # 当前阶段内考官已完成的说话轮数
        self._turn_had_audio = False      # 本轮考官是否真发过声（空轮不计数）
        self._prep_task: asyncio.Task | None = None

    def on_model_audio(self) -> None:
        """考官音频帧到达（bridge 下行同步调）：标记本轮真说了话。

        真冒烟实锤：Live 偶发**无音频的 turn_complete**（如对导演文本指令的
        回执轮）——若照常计数，FSM 会抢跑、指令堆进未完成的生成流导致会话
        卡死。只有真出过声的轮才推进状态机。
        """
        self._turn_had_audio = True

    def on_interrupted(self) -> None:
        """考官被打断（bridge 下行 sc.interrupted）：清掉本轮发声标记。

        否则被打断轮残留的 True 会让下一个空回执 turn_complete 被误计为
        真实考官轮，击穿空轮防御（review C1）。
        """
        self._turn_had_audio = False

    # —— 生命周期 —— #

    async def start(self, websocket, session) -> None:
        """建链后调用：宣布 P1 并让考官开场。"""
        await websocket.send_json({"type": "part_change", "part": "p1"})
        await self._direct(session, _OPENING_PROMPT)

    async def on_turn_complete(self, websocket, session) -> None:
        """考官说完一轮（bridge 下行 turn_complete 之后调）——唯一推进时钟。

        空轮（本轮没有任何考官音频）不计数：见 on_model_audio。
        """
        if not self._turn_had_audio:
            logger.info("director: 空 turn_complete（无考官音频），不计轮")
            return
        self._turn_had_audio = False
        self._examiner_turns += 1
        if self.state == "p1" and self._examiner_turns >= P1_EXAMINER_TURNS:
            await self._enter_p2_prep(websocket, session)
        elif self.state == "p2_talk" and self._examiner_turns >= 2:
            # 邀请轮已过，本轮 = 追问问出（预埋在 _P2_TALK_PROMPT）→ 候选人答追问；
            # 此刻预埋「收追问 + 转 P3」剧本，考官下一轮照办
            await self._set_state(websocket, "p2_followup")
            await self._direct(session, _P2_TO_P3_PROMPT)
        elif self.state == "p2_followup":
            # 考官完成「收追问 + P3 开场问」这一轮 → 正式进入 P3 问答
            await self._set_state(websocket, "p3")
        elif self.state == "p3" and self._examiner_turns >= P3_EXAMINER_TURNS:
            await self._set_state(websocket, "done")
            await self._direct(session, _CLOSING_PROMPT)

    async def on_ready(self, websocket, session) -> None:
        """前端「我准备好了」：提前结束备题（与 60s 计时器先到先得）。"""
        await self._end_prep(websocket, session)

    def cancel_timers(self) -> None:
        """会话收束时调：取消未触发的备题计时器，不留孤儿任务。"""
        if self._prep_task is not None:
            self._prep_task.cancel()
            self._prep_task = None

    # —— 内部转场 —— #

    async def _enter_p2_prep(self, websocket, session) -> None:
        # 先停输入再走 await 链：否则四个 await 点的窗口里备题嘀咕会漏进样本（review S2）
        self.input_paused = True
        await self._set_state(websocket, "p2_prep")
        await self._direct(
            session, _P2_INTRO_TEMPLATE.format(topic=self._card["text"])
        )
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
        await websocket.send_json(
            {"type": "start_prep_timer", "seconds": PREP_SECONDS}
        )
        self._prep_task = asyncio.create_task(self._prep_timeout(websocket, session))

    async def _prep_timeout(self, websocket, session) -> None:
        await asyncio.sleep(PREP_SECONDS)
        await self._end_prep(websocket, session)

    async def _end_prep(self, websocket, session) -> None:
        """计时到点 / ready 提前——只有仍在 p2_prep 才转场（查重防双触发）。

        ⚠️ 绝不能 cancel 当前任务自己：计时器路径里 `_end_prep` 就跑在
        `_prep_task` 上，自取消的 CancelledError 会在随后 `_direct` 的网络
        await 点注入，把发往 Live 的指令帧截断在半截——服务端 1007/1008
        杀连接（真冒烟实锤的根因，review W1）。ready 路径才真取消计时器。
        """
        if self.state != "p2_prep":
            return
        self.input_paused = False
        task, self._prep_task = self._prep_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        await self._set_state(websocket, "p2_talk")
        await self._direct(session, _P2_TALK_PROMPT)

    async def _set_state(self, websocket, state: str) -> None:
        self.state = state
        self._examiner_turns = 0
        await websocket.send_json({"type": "part_change", "part": state})
        logger.info("director: 转场 → %s", state)

    @staticmethod
    async def _direct(session, prompt: str) -> None:
        """注入方括号导演提示：作为文本回合发给 Live，考官按指示行动但不读出。"""
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
            turn_complete=True,
        )
