"""demo seed（SCHEMA §5.3）：预置 7 条历史会话，让进步曲线开箱可见。

一次现场会话只有一个点、画不出曲线——seed 把流利度设计成向好爬升（wpm 升 /
静默比降 / 填充词降），雅思方式 A 另含 band 5.5→6.0→6.5；现场真会话叠为最新点。
seed 行以 `sessions.is_seed=1` 诚实标注（Library 显示"演示数据"），可点开看报告，
无音频回放（audio_path 为空）。TTS 预生成另见 `python -m app.tts`。

用法：`uv run python -m app.seed`
  - 幂等：先物理删除全部既有 seed 行（CASCADE 连带报告）再重插；
    日期相对当下回填（最近一条 2 天前），重跑即刷新曲线时效。
  - `--purge`：只删不插（演示后还原干净库）。

report_json 经 `Report` pydantic 模型构造——与真流水线产物同 schema，
报告页渲染零特判；方式 A overall 用真聚合函数算，规则永不漂移。
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

from app import crud
from app.db import get_connection, init_db
from app.judge.aggregate import aggregate_overall_band
from app.report import (
    CommonPattern,
    Diagnostics,
    Dimension,
    Dimensions,
    FossilizedError,
    FrequentError,
    PracticeSummary,
    Report,
    Rewrite,
    SelfCorrectionItem,
    SyntacticAnalysis,
    TopPriority,
)

logger = logging.getLogger(__name__)


def _dim(band: float, evidence: list[str], match: str, tips: list[str]) -> Dimension:
    return Dimension(
        band=band, evidence=evidence, descriptor_match=match, suggestions=tips
    )


# —— 7 条 seed 的数据面（时间升序；流利度全程向好，方式 A band 5.5→6.0→6.5）—— #
# days_ago 相对运行时刻回填 started_at；客观信号列与 report_json 同源（同一 spec）。
SEED_SPECS: list[dict] = [
    {
        "id": "seed-01",
        "days_ago": 16,
        "mode": "ielts", "sub_mode": "exam", "scenario_case": None,
        "duration_s": 690.0, "speaking_time_s": 392.0, "recordings": 11,
        "wpm": 84.0, "silence_ratio": 0.42, "filler_pm": 9.6,
        "ttr": 0.42, "error_rate": 4.8,
        "dims": Dimensions(
            fluency_coherence=_dim(
                5.5,
                ["I think... you know... it is... like a big problem"],
                "命中 band 5「依赖重复与自我更正维持语流」；卡在 band 6「停顿多在找语法而非内容」",
                ["先用简单句保住语流，再逐步加从句", "用 1 秒留白替代 you know 填充"],
            ),
            lexical_resource=_dim(
                5.0,
                ["very good", "very big", "very important"],
                "命中 band 5「词汇有限但够日常话题」；卡在 band 6「少见搭配与释义能力」",
                ["把 very + 形容词换成单词强化（huge / crucial）"],
            ),
            grammatical_range_accuracy=_dim(
                5.5,
                ["she teach Chinese in my school"],
                "命中 band 5「基础句型尚可、复杂句错误密集」；卡在 band 6「错误偶发但不致误解」",
                ["每天 10 句三单口头操练，录音自查"],
            ),
            pronunciation=_dim(
                6.0,
                ["the most important sing in my life is family"],
                "命中 band 6「整体可懂、个别音素失准（th 读作 s，转写成 sing）」；卡在 band 7「重音与语调起伏不足」",
                ["对镜练 th 咬舌位，每天 5 分钟"],
            ),
        ),
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="口头禅 you know 作填充", count=6)],
            syntactic_analysis=SyntacticAnalysis(
                observation="9 个主句中 7 个以 'I think I...' 开头，句式单一",
                suggestion="试用 What I find interesting is... 或介词短语开头",
            ),
            frequent_errors=[
                FrequentError(category="grammar", desc="三单动词一致", count=5),
                FrequentError(category="grammar", desc="过去时误用现在时", count=4),
            ],
            fossilized_errors=[
                FossilizedError(
                    desc="主谓一致反复出错",
                    occurrences=["she teach Chinese", "my friend like music"],
                )
            ],
            self_corrections=[
                SelfCorrectionItem(initial="we we all need", corrected="we all need to learn")
            ],
            top_priorities=[
                TopPriority(
                    title="三单动词一致", severity="high",
                    explanation="高频且已有固化迹象，直接拉低 Grammatical Range & Accuracy",
                    examples=["she teach Chinese"], quick_fix="说到 he/she/it 时在脑中默加 -s",
                ),
                TopPriority(
                    title="填充词依赖", severity="medium",
                    explanation="you know 每分钟近一次，打断语流与连贯",
                    examples=["it is, you know, like a big problem"],
                    quick_fix="想词时改用短暂停顿，不出声",
                ),
            ],
            rewrites=[
                Rewrite(
                    original="I think science is curiosity",
                    rewrite="Science is driven by curiosity",
                    reason="更简洁，用 driven by 搭配替代 I think 套壳",
                ),
                Rewrite(
                    original="my hometown is very good place",
                    rewrite="My hometown is a lovely place to grow up in",
                    reason="补冠词，very good 升级为具体形容",
                ),
            ],
        ),
    },
    {
        "id": "seed-02",
        "days_ago": 14,
        "mode": "scenario", "sub_mode": None, "scenario_case": "ordering",
        "duration_s": 270.0, "speaking_time_s": 128.0, "recordings": 6,
        "wpm": 88.0, "silence_ratio": 0.40, "filler_pm": 8.9,
        "ttr": 0.44, "error_rate": 4.2,
        "dims": None,
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="直接祈使索取（give me / I want），缺礼貌句式", count=4)],
            syntactic_analysis=SyntacticAnalysis(
                observation="点单全部用祈使句（give me / I want），缺少疑问式委婉表达",
                suggestion="点餐场景优先 Could I have... / I'd like... 句式",
            ),
            frequent_errors=[
                FrequentError(category="pragmatics", desc="缺礼貌缓和语（please / could）", count=4),
                FrequentError(category="grammar", desc="可数名词漏冠词", count=3),
            ],
            fossilized_errors=[],
            self_corrections=[
                SelfCorrectionItem(initial="I want eat", corrected="I want to eat something")
            ],
            top_priorities=[
                TopPriority(
                    title="礼貌句式", severity="high",
                    explanation="服务场景里祈使句显得生硬，影响交际效果",
                    examples=["Give me the menu"],
                    quick_fix="开口前套用 Could I... 模板",
                ),
            ],
            rewrites=[],   # 情景不出改写示范（用户决策 2026-06-07）
            summary=(
                "全程独立完成点单、没有冷场，交流意愿很好。主要问题是祈使句点单"
                "（Give me...）显得生硬，礼貌缓和语（please / could）缺失最高频。"
                "下次开口前先套 Could I have... / I'd like... 句式，把礼貌表达练成开口本能。"
            ),
        ),
    },
    {
        "id": "seed-03",
        "days_ago": 11,
        "mode": "ielts", "sub_mode": "module_p1", "scenario_case": None,
        "duration_s": 210.0, "speaking_time_s": 134.0, "recordings": 6,
        "wpm": 93.0, "silence_ratio": 0.36, "filler_pm": 7.8,
        "ttr": 0.46, "error_rate": 3.6,
        "dims": None,
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="单句短答不扩展", count=5)],
            syntactic_analysis=SyntacticAnalysis(
                observation="Part 1 问答平均仅 8 词/答，缺扩展（原因 / 例子）",
                suggestion="用 because + 一个具体例子把每答撑到 2–3 句",
            ),
            frequent_errors=[
                FrequentError(category="grammar", desc="一般过去时形态错误", count=3),
                FrequentError(category="fluency", desc="句首 uh 起步", count=4),
            ],
            fossilized_errors=[],
            self_corrections=[
                SelfCorrectionItem(initial="I go there last year", corrected="I went there last year")
            ],
            top_priorities=[
                TopPriority(
                    title="答案扩展", severity="high",
                    explanation="单句作答暴露不了词汇与语法广度，Part 1 也要给考官素材",
                    examples=["Yes, I like reading."],
                    quick_fix="每答跟一句 because... 或 for example...",
                ),
            ],
            rewrites=[
                Rewrite(
                    original="Yes, I like reading.",
                    rewrite="Yes, I'm quite into reading — mostly detective novels, because the plots keep me hooked.",
                    reason="表态 + 具体类型 + 原因，三步扩展模板",
                ),
            ],
        ),
    },
    {
        "id": "seed-04",
        "days_ago": 9,
        "mode": "ielts", "sub_mode": "exam", "scenario_case": None,
        "duration_s": 720.0, "speaking_time_s": 421.0, "recordings": 11,
        "wpm": 99.0, "silence_ratio": 0.33, "filler_pm": 6.5,
        "ttr": 0.49, "error_rate": 3.1,
        "dims": Dimensions(
            fluency_coherence=_dim(
                6.0,
                ["Well, to be honest, I hadn't thought about it before, but..."],
                "命中 band 6「能展开但偶有重复」；卡在 band 7「长段落仍靠 and 串联」",
                ["练 however / on top of that 等衔接替换 and"],
            ),
            lexical_resource=_dim(
                5.5,
                ["it makes me feel relax"],
                "命中 band 5–6 之间「日常词汇够用、搭配仍有错」；卡在 band 6「释义绕行能力不稳」",
                ["积累 -ed/-ing 形容词对（relaxed/relaxing）"],
            ),
            grammatical_range_accuracy=_dim(
                6.0,
                ["If I had more time, I will travel more"],
                "命中 band 6「简单句准确、复杂句出错（虚拟式混搭）」；卡在 band 7「条件句与从句控制」",
                ["每天口头造 3 个 if 虚拟句"],
            ),
            pronunciation=_dim(
                6.5,
                ["it is wery important for my health"],
                "命中 band 6「可懂度好、偶有音素替换（v 读作 w）」；卡在 band 7「缺语调起伏标记重点」",
                ["朗读时给关键词刻意升调"],
            ),
        ),
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="and... and... 链式串句", count=4)],
            syntactic_analysis=SyntacticAnalysis(
                observation="长答案以 and 平行堆叠为主，主从复合句占比低",
                suggestion="把第二个 and 换成 which / because 从句",
            ),
            frequent_errors=[
                FrequentError(category="grammar", desc="条件句时态混搭", count=3),
                FrequentError(category="lexis", desc="-ed/-ing 形容词混用", count=2),
            ],
            fossilized_errors=[
                FossilizedError(
                    desc="relax 当形容词用",
                    occurrences=["feel relax", "it's very relax"],
                )
            ],
            self_corrections=[
                SelfCorrectionItem(initial="if I have... had more time", corrected="if I had more time")
            ],
            top_priorities=[
                TopPriority(
                    title="条件句时态", severity="high",
                    explanation="虚拟语气混搭在 Part 3 高频出现，封顶 GRA band 6",
                    examples=["If I had more time, I will travel more"],
                    quick_fix="if 过去式后固定接 would",
                ),
                TopPriority(
                    title="衔接词多样化", severity="medium",
                    explanation="and 链式连接拉低 Coherence 上限",
                    examples=["...and I like it and it's cheap and..."],
                    quick_fix="第二个 and 起换 which / plus / on top of that",
                ),
            ],
            rewrites=[
                Rewrite(
                    original="it makes me feel relax",
                    rewrite="it helps me unwind",
                    reason="unwind 一词到位，避开 relax 词性坑",
                ),
            ],
        ),
    },
    {
        "id": "seed-05",
        "days_ago": 6,
        "mode": "scenario", "sub_mode": None, "scenario_case": "meeting",
        "duration_s": 330.0, "speaking_time_s": 172.0, "recordings": 7,
        "wpm": 105.0, "silence_ratio": 0.30, "filler_pm": 5.4,
        "ttr": 0.52, "error_rate": 2.6,
        "dims": None,
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="先铺背景细节、结论后置", count=3)],
            syntactic_analysis=SyntacticAnalysis(
                observation="进度汇报先铺垫细节再给结论，听者要等 30 秒才知道状态",
                suggestion="职场汇报结论先行：先一句 on track / blocked，再展开",
            ),
            frequent_errors=[
                FrequentError(category="pragmatics", desc="模糊量词（some, a lot）代替数据", count=3),
                FrequentError(category="grammar", desc="现在完成时漏 have", count=2),
            ],
            fossilized_errors=[],
            self_corrections=[
                SelfCorrectionItem(initial="we finish the design", corrected="we have finished the design")
            ],
            top_priorities=[
                TopPriority(
                    title="结论先行", severity="high",
                    explanation="会议场景信息结构比语法更影响沟通效率",
                    examples=["So... there are many things... and finally we did it"],
                    quick_fix="开口第一句固定为 The short version is...",
                ),
            ],
            rewrites=[],   # 情景不出改写示范（用户决策 2026-06-07）
            summary=(
                "进度汇报信息完整，还出现了主动自我更正（we finish → we have finished），"
                "语法意识在上线。最大短板是结论后置——听者要等 30 秒才知道项目状态，"
                "模糊量词（some / a lot）也削弱说服力。下次第一句固定 The short version is...，"
                "先给结论再展开细节。"
            ),
        ),
    },
    {
        "id": "seed-06",
        "days_ago": 4,
        "mode": "ielts", "sub_mode": "module_p2", "scenario_case": None,
        "duration_s": 240.0, "speaking_time_s": 158.0, "recordings": 2,
        "wpm": 112.0, "silence_ratio": 0.27, "filler_pm": 4.6,
        "ttr": 0.55, "error_rate": 2.1,
        "dims": None,
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="cue card bullets 乱序展开、丢主线", count=2)],
            syntactic_analysis=SyntacticAnalysis(
                observation="长谈能撑满 2 分钟，但 bullets 间缺过渡句，话题跳切生硬",
                suggestion="bullet 切换时用 As for... / What made it special was...",
            ),
            frequent_errors=[
                FrequentError(category="lexis", desc="高频动词 get/do 泛用", count=3),
            ],
            fossilized_errors=[],
            self_corrections=[
                SelfCorrectionItem(initial="I get many feelings", corrected="it left a deep impression on me")
            ],
            top_priorities=[
                TopPriority(
                    title="长谈结构信号词", severity="medium",
                    explanation="结构清晰能直接抬 Coherence，2 分钟独白尤其吃结构",
                    examples=["...em, and the place, the place is..."],
                    quick_fix="按 cue card 四个 bullet 各配一个固定开场短语",
                ),
            ],
            rewrites=[
                Rewrite(
                    original="I get many feelings about this trip",
                    rewrite="That trip left a lasting impression on me",
                    reason="leave an impression 地道搭配替代 get feelings",
                ),
            ],
        ),
    },
    {
        "id": "seed-07",
        "days_ago": 2,
        "mode": "ielts", "sub_mode": "exam", "scenario_case": None,
        "duration_s": 750.0, "speaking_time_s": 447.0, "recordings": 12,
        "wpm": 118.0, "silence_ratio": 0.24, "filler_pm": 3.8,
        "ttr": 0.58, "error_rate": 1.6,
        "dims": Dimensions(
            fluency_coherence=_dim(
                6.5,
                ["That's an interesting question — I'd say it depends on the context..."],
                "命中 band 6–7「语流自然、衔接多样」；卡在 band 7「抽象话题仍偶有重启」",
                ["Part 3 抽象题先给立场句争取组织时间"],
            ),
            lexical_resource=_dim(
                6.5,
                ["a double-edged sword", "strike a balance"],
                "命中 band 7「习语初现、释义自如」；卡在 band 7 稳定性「话题词汇深度不均」",
                ["按话题群补高级搭配（environment / technology）"],
            ),
            grammatical_range_accuracy=_dim(
                6.0,
                ["I bought new phone last month"],
                "命中 band 6「复杂结构尝试多、小错不碍理解（冠词脱落）」；卡在 band 7「错误句占比仍超半」",
                ["录音回听标记冠词缺位，针对性纠偏"],
            ),
            pronunciation=_dim(
                7.0,
                ["What I'd say is — it really depends on the context"],
                "命中 band 7「语调有表现力、连读自然、可懂度高」；卡在 band 8「个别弱读不稳定」",
                ["跟读练 function words 弱读"],
            ),
        ),
        "diagnostics_judge": dict(
            common_patterns=[CommonPattern(pattern="抽象题偶有句子重启", count=2)],
            syntactic_analysis=SyntacticAnalysis(
                observation="从句嵌套与被动语态自发出现，句式多样性显著提升",
                suggestion="保持现有广度，把准确率从约 50% 推向 70%",
            ),
            frequent_errors=[
                FrequentError(category="grammar", desc="冠词脱落", count=2),
            ],
            fossilized_errors=[],
            self_corrections=[
                SelfCorrectionItem(
                    initial="the technology bring", corrected="technology brings"
                )
            ],
            top_priorities=[
                TopPriority(
                    title="冠词系统", severity="medium",
                    explanation="剩余主要失分点，修复后 GRA 可冲 band 7",
                    examples=["I bought new phone last month"],
                    quick_fix="单数可数名词出口前默查 a/the",
                ),
            ],
            rewrites=[
                Rewrite(
                    original="Technology is good and bad",
                    rewrite="Technology is a double-edged sword — it cuts both ways",
                    reason="习语表达立场，Part 3 高分句式",
                ),
            ],
        ),
    },
]


def _build_report(spec: dict) -> Report:
    """按 spec 组装与真流水线同形态的 Report（方式 A 才有 band，overall 走真聚合）。"""
    report = Report(
        practice_summary=PracticeSummary(
            speaking_time_s=spec["speaking_time_s"],
            sessions=1,
            recordings=spec["recordings"],
        ),
        dimensions=spec["dims"],
        diagnostics=Diagnostics(
            **spec["diagnostics_judge"],
            vocabulary_diversity_pct=round(spec["ttr"] * 100, 1),
        ),
    )
    if report.dimensions is not None:
        report.overall_band = aggregate_overall_band(report.dimensions)
    return report


def _started_at(now: datetime, days_ago: int) -> str:
    """生成与 SQLite 默认格式一致的 started_at（毫秒 + Z）。

    要求 tz-aware：naive datetime 经 astimezone 会按本机时区解释，时间戳漂移
    且无声（review W1）——直接拒绝。
    """
    if now.tzinfo is None:
        raise ValueError("now 必须带时区（如 datetime.now(timezone.utc)）")
    dt = (now - timedelta(days=days_ago)).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def purge_seeds() -> int:
    """物理删除全部 seed 行（CASCADE 连带 turns/reports），返回删除条数。"""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE is_seed = 1")
        return cur.rowcount


def seed(now: datetime | None = None) -> list[str]:
    """幂等播种：先清旧 seed 再插 7 条；返回插入的 session id 列表。

    逐条插入非整体事务：中途被杀会留部分 seed 行，但重跑先 purge 即自愈——
    demo 单机脚本不为此引入跨连接事务复杂度（review W2 记录在案）。
    """
    removed = purge_seeds()
    if removed:
        logger.info("已清除旧 seed 行 %d 条", removed)

    now = now or datetime.now(timezone.utc)
    inserted: list[str] = []
    for spec in SEED_SPECS:
        report = _build_report(spec)
        crud.create_session(
            session_id=spec["id"],
            mode=spec["mode"],
            sub_mode=spec["sub_mode"],
            scenario_case=spec["scenario_case"],
            audio_path=None,                    # 演示数据无音频回放（SCHEMA §5.3）
            duration_s=spec["duration_s"],
            status="completed",
            is_seed=True,
        )
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET started_at = ? WHERE id = ?",
                (_started_at(now, spec["days_ago"]), spec["id"]),
            )
        crud.create_report(
            session_id=spec["id"],
            mode=spec["mode"],
            overall_band=report.overall_band,
            fc_band=report.dimensions.fluency_coherence.band if report.dimensions else None,
            lr_band=report.dimensions.lexical_resource.band if report.dimensions else None,
            gra_band=report.dimensions.grammatical_range_accuracy.band if report.dimensions else None,
            pron_band=report.dimensions.pronunciation.band if report.dimensions else None,
            wpm=spec["wpm"],
            silence_ratio=spec["silence_ratio"],
            filler_pm=spec["filler_pm"],
            ttr=spec["ttr"],
            error_rate=spec["error_rate"],
            report_json=report.model_dump_json(),
        )
        inserted.append(spec["id"])
    logger.info("seed 完成：插入 %d 条历史会话（%s）", len(inserted), ", ".join(inserted))
    return inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="demo seed：预置历史会话与报告")
    parser.add_argument("--purge", action="store_true", help="只清除 seed 行，不重插")
    args = parser.parse_args()

    init_db()
    if args.purge:
        print(f"已清除 seed 行 {purge_seeds()} 条")
    else:
        ids = seed()
        print(f"seed 完成：{len(ids)} 条（雅思 A band 5.5→6.0→6.5，流利度爬升）")
