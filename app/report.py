"""课后报告结构化 schema（PRD §6.2）。

一次 judge 调用产出整份报告。雅思含四维 band + overall_band（情景为 None）；
诊断层所有模式共享。本 schema 也直接用作 Gemini 结构化输出 schema。
"""

from pydantic import BaseModel, Field


class PracticeSummary(BaseModel):
    speaking_time_s: float
    sessions: int
    recordings: int


# —— 雅思四维 —— #
class Dimension(BaseModel):
    band: float = Field(ge=0, le=9)
    evidence: list[str] = Field(description="逐字引用考生原话；引不出原话则不下判断")
    descriptor_match: str = Field(description="命中 band X 哪条、卡在 X+1 哪条")
    suggestions: list[str]


class Dimensions(BaseModel):
    fluency_coherence: Dimension
    lexical_resource: Dimension
    grammatical_range_accuracy: Dimension
    pronunciation: Dimension


# —— live FC 反馈实录（仅情景，系统确定性组装）—— #
class LiveCorrection(BaseModel):
    """会话内 grammar_note 一次纠错实录（original→fixed 对照 + note 错误类型）。"""

    original: str
    fixed: str
    note: str
    spoken: bool   # True=当场口头纠正过；False=控频压掉、仅卡片


class LiveTeaching(BaseModel):
    """会话内 language_help 一次中文求助实录（chinese→english + 场景例句）。"""

    kind: str      # mixed_cn | full_sentence_cn | explicit_ask
    chinese: str
    english: str
    example: str


class LiveFeedback(BaseModel):
    """情景会话内 FC 反馈实录（grammar_note / language_help），系统确定性组装。

    不进 JudgeReport schema——数据本就结构化（tool 调用参数原样），让 LLM
    转述只会引入漂移；judge 只把它当输入材料（prompt 注入），报告字段由
    后端直接落。仅情景 live 会话非空：雅思无 tools、方式 B 无 Live。
    """

    corrections: list[LiveCorrection]
    teachings: list[LiveTeaching]


# —— 诊断层（所有模式共享）—— #
class CommonPattern(BaseModel):
    pattern: str
    count: int


class SyntacticAnalysis(BaseModel):
    observation: str
    suggestion: str


class FrequentError(BaseModel):
    category: str
    desc: str
    count: int


class FossilizedError(BaseModel):
    desc: str
    occurrences: list[str]


class SelfCorrectionItem(BaseModel):
    initial: str
    corrected: str


class TopPriority(BaseModel):
    title: str
    severity: str  # high | medium | low
    explanation: str
    examples: list[str]
    quick_fix: str


class Rewrite(BaseModel):
    original: str
    rewrite: str
    reason: str


class JudgeDiagnostics(BaseModel):
    """judge 结构化输出的诊断层：只含 LLM 真正该产出的字段。

    vocabulary_diversity_pct 不在此处——它就是客观信号的 TTR×100，由后端确定性
    回填（P1 收口），让 LLM 产出徒增漂移面。
    """

    common_patterns: list[CommonPattern]
    syntactic_analysis: SyntacticAnalysis
    frequent_errors: list[FrequentError]
    fossilized_errors: list[FossilizedError]
    self_corrections: list[SelfCorrectionItem]
    top_priorities: list[TopPriority]
    rewrites: list[Rewrite]
    # 情景对话报告末尾总结（一段简短中文：肯定亮点 → 点出主要问题 → 给提升方向）。
    # 仅情景产出；雅思由 run_judge 确定性置 None（已有 top_priorities，不重复一份总结）。
    summary: str | None = None


class Diagnostics(JudgeDiagnostics):
    """完整诊断层（对前端的 Report shape）：judge 产出 + 后端回填字段。"""

    vocabulary_diversity_pct: float | None = None   # 后端回填（TTR×100），judge 不产出


class JudgeReport(BaseModel):
    """judge 结构化输出 schema（response_schema 用，P1 收口）。

    只让 LLM 产出 dimensions + 诊断层。practice_summary / overall_band /
    unscorable* / vocabulary_diversity_pct 全部由系统确定性设置或回填——
    不进 judge schema，LLM 想填也没地方填。
    """

    dimensions: Dimensions | None = None   # 仅雅思；judge 拒评时为 None
    diagnostics: JudgeDiagnostics


class Report(BaseModel):
    practice_summary: PracticeSummary
    dimensions: Dimensions | None = None   # 仅雅思
    overall_band: float | None = None      # 仅雅思；情景不聚合、不出总分
    # 雅思无法产出 band 时为 True（静音 / 非英语 / 录音问题，judge 依 grounding 铁律拒评）。
    # 此时 dimensions/overall_band 为 None 但诊断层仍保留——区别于情景对话的「设计上无 band」。
    # 系统确定性设置（同 overall_band），不交给 LLM 自填。
    unscorable: bool = False
    unscorable_reason: str | None = None
    diagnostics: Diagnostics
    # 会话内 FC 反馈实录：仅情景 live 会话且有事件时非空（系统组装，非 LLM 产出）。
    live_feedback: LiveFeedback | None = None
