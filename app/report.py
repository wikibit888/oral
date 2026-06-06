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


class Diagnostics(BaseModel):
    common_patterns: list[CommonPattern]
    syntactic_analysis: SyntacticAnalysis
    frequent_errors: list[FrequentError]
    fossilized_errors: list[FossilizedError]
    self_corrections: list[SelfCorrectionItem]
    vocabulary_diversity_pct: float
    top_priorities: list[TopPriority]
    rewrites: list[Rewrite]


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
