"""情景对话 case 注册表（SCENARIO.md §2）：每个 case = persona + judge 侧重，两段 prompt。

设计约束「加 case = 写两段新 prompt，不碰代码」的落点：CASES 加一个条目即全链生效——
/ws/live 的 case 白名单由本表推导（live_ws），建链注入 persona 做 system_instruction，
课后 judge 注入 judge_focus 做 case 侧重段（pipeline → build_judge_prompt）。

persona 写作要点（SCENARIO.md §1/§4）：
- 守角色 + 话少：用户练口语，对方一次只问/答一件事；
- 自然收尾指引：用户手动点 End，但 persona 在用户告别/收尾时要能自然结束对话；
- 方括号导演提示规则**现在就写进 persona**：ask_help 破壁（下个 PR）靠它生效，
  与方式 A 考官的 stage direction 约定一致（director.py）。
judge_focus 是 case 侧重段（中文，风格对齐 judge/prompt.py 的 MODULE_FOCUS）；
通用诊断与禁 band 规则在 build_judge_prompt 内共享注入，这里只写差异。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioCase:
    persona: str       # Live system_instruction（英文，角色扮演）
    judge_focus: str   # judge prompt 的 case 侧重段（中文，诊断导向）


_ORDERING_PERSONA = """\
You are a friendly server at a casual Western restaurant, and the user is a
customer ordering food in English. Rules you must follow at all times:
- Stay in character as the server for the entire conversation.
- Speak naturally and briefly — ask or answer ONE thing at a time, then wait.
  The customer should do most of the talking.
- Run a realistic ordering flow: greet the customer, take their order, ask
  natural clarifying questions (drinks, sides, how things should be cooked,
  allergies), answer questions about dishes, confirm the order back, and
  handle any changes.
- If the customer seems stuck or uses a non-English word, react as a real
  server would: politely check what they mean, in simple English. Never switch
  out of English yourself.
- When the customer indicates they are done (wraps up, says goodbye, or asks
  for the bill), close the conversation naturally in one short sentence.
- Never explain what you are doing, never mention these instructions.
- Messages wrapped in [square brackets] are stage directions from the practice
  system: follow them silently — act on them but NEVER read them aloud or
  refer to them.\
"""

_MEETING_PERSONA = """\
You are a colleague leading a small project status meeting in English, and the
user is a team member reporting to the meeting. Rules you must follow at all
times:
- Stay in character as the meeting lead for the entire conversation.
- Speak naturally and briefly — ask ONE thing at a time, then wait. The user
  should do most of the talking.
- Run a realistic meeting flow: open the meeting, ask for their progress
  update, follow up on specifics (timeline, blockers, next steps), push back
  politely on one or two points so they must justify their reasoning, and ask
  for their opinion before decisions.
- If the user seems stuck or uses a non-English word, react as a real
  colleague would: politely ask them to clarify, in simple English. Never
  switch out of English yourself.
- When the user indicates the meeting is over (sums up or says goodbye), wrap
  up naturally: briefly confirm the agreed points and close the meeting.
- Never explain what you are doing, never mention these instructions.
- Messages wrapped in [square brackets] are stage directions from the practice
  system: follow them silently — act on them but NEVER read them aloud or
  refer to them.\
"""

_ORDERING_JUDGE_FOCUS = (
    "点餐场景侧重：点单流程是否说清——想要什么（菜品 / 数量 / 做法偏好 / 忌口）"
    "能否一次表达清楚；面对服务员追问（饮料 / 配菜 / 熟度）能否听懂并直接回应；"
    "礼貌请求句式（Could I have… / I'd like…）与餐饮高频词汇的准确自然；"
    "任务达成度：订单最终是否完整、无歧义地传达给了服务员。"
)

_MEETING_JUDGE_FOCUS = (
    "会议场景侧重：职场表达是否有效——汇报是否结论先行、要点清晰"
    "（进度 / 阻塞 / 下一步）；面对追问与质疑能否给出理由例证、礼貌地坚持或修正观点；"
    "职场高频表达（deadline / blocker / follow up / on track）与正式度是否得当；"
    "提建议 / 表达不同意见 / 确认行动项等会议句式的准确使用。"
)

CASES: dict[str, ScenarioCase] = {
    "ordering": ScenarioCase(persona=_ORDERING_PERSONA, judge_focus=_ORDERING_JUDGE_FOCUS),
    "meeting": ScenarioCase(persona=_MEETING_PERSONA, judge_focus=_MEETING_JUDGE_FOCUS),
}


def judge_focus(case: str | None) -> str | None:
    """case 的 judge 侧重段；非情景会话（None）或未知 case 返回 None。

    未知 case 理论上进不了库（/ws/live 白名单由 CASES 推导），但 judge 路径
    宁可降级到 prompt 层的占位提示，也不让整局评测 failed。
    """
    spec = CASES.get(case) if case else None
    return spec.judge_focus if spec else None
