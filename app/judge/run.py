"""结构化 judge 调用：一次 Gemini 调用产出整份报告。

护城河铁律落地：
- temperature=0 + 结构化输出（response_schema=JudgeReport，P1 收口：LLM 只产出
  dimensions + 诊断层；practice_summary / overall_band / unscorable* /
  vocabulary_diversity_pct 全部由系统确定性设置或回填）；
- 雅思额外喂音频切片让模型听发音判可懂度——只挑 **2–3 段最长用户切片**
  （SCHEMA §3），优先引用 Files API 预上传的 file URI（省掉课后上传大音频），
  无 URI 时回退 inline bytes；情景只走文字诊断；
- overall_band 由系统按四维确定性聚合（judge 不自算；信号≠成绩）；
- 数字 band 只在雅思方式 A（sub_mode=exam）：方式 B（module_pX）四维仅作内部
  诊断依据、最终置空（descriptor 对齐诊断，IELTS.md §3）；情景强制无 band；
- 情景报告结构（用户决策 2026-06-07）：rewrites 强制清空（会话内已即时纠正）、
  summary 仅情景保留（雅思置 None）——系统强制，不靠 LLM 自觉；
- 雅思 judge 拒评（dimensions=None）标记 unscorable 而非抛错，保留诊断层、不哑失败。
"""

import logging
import time
from dataclasses import asdict
from pathlib import Path

from google import genai
from google.genai import errors, types

from app.config import settings
from app.judge.aggregate import aggregate_overall_band, round_to_half
from app.judge.prompt import build_judge_prompt
from app.models import AudioClip, Transcript
from app.report import Diagnostics, Dimensions, JudgeReport, PracticeSummary, Report
from app.signals import ObjectiveSignals

logger = logging.getLogger(__name__)

# 雅思拒评时给用户的统一说明（系统设置，不让 LLM 自由发挥）。
UNSCORABLE_REASON = "无法评分：未检出可评的英语口语内容（可能是静音、非英语或录音问题），请重录后再试。"

# judge 判发音只喂最长的 N 段用户切片（SCHEMA §3：不喂全程音频）。
MAX_PRONUNCIATION_CLIPS = 3

AUDIO_MIME = "audio/wav"

# judge 上游 5xx（联调多次实测 503 高负载）按此退避重试；temp=0 重试无副作用。
JUDGE_RETRY_BACKOFF_S = (2, 5)

_genai_client: genai.Client | None = None


def _client() -> genai.Client:
    """懒加载进程内单例 Gemini 客户端。

    代理走 http_options 传给底层 httpx，不污染进程 os.environ（W1）。
    GEMINI_PROXY=none/off 或留空即直连。
    """
    global _genai_client
    if _genai_client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY 未配置，无法调用 judge（检查 .env）。")
        http_options: types.HttpOptions | None = None
        proxy = settings.gemini_proxy
        if proxy and proxy.strip().lower() not in ("none", "off", "0", ""):
            http_options = types.HttpOptions(client_args={"proxy": proxy})
        _genai_client = genai.Client(api_key=settings.gemini_api_key, http_options=http_options)
    return _genai_client


def _generate_with_retry(contents: list) -> types.GenerateContentResponse:
    """调一次 judge 生成；上游 5xx（ServerError）按退避序列重试后仍败则上抛。

    联调多次实测 judge 模型 503 高负载、稍候即通——不重试会把瞬态故障固化成
    用户可见的 failed 报告。只重试 5xx：4xx（配额/参数）重试无意义；
    temperature=0 + 结构化输出，重试不引入漂移。
    """
    for backoff in (*JUDGE_RETRY_BACKOFF_S, None):
        try:
            return _client().models.generate_content(
                model=settings.judge_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=JudgeReport,
                ),
            )
        except errors.ServerError as e:
            if backoff is None:
                raise
            logger.warning("judge 上游 5xx，%ss 后重试：%r", backoff, e)
            time.sleep(backoff)


def upload_clip(path: str) -> str | None:
    """切片预上传 Gemini Files API，返回 file URI（增量流水线：切片落地即上传）。

    失败降级而不阻断会话：返回 None，judge 调用时对该切片回退 inline bytes。
    无 API key（如离线测试）直接跳过，不报错。
    """
    if not settings.gemini_api_key:
        return None
    try:
        f = _client().files.upload(
            file=path, config=types.UploadFileConfig(mime_type=AUDIO_MIME)
        )
    except Exception:
        logger.warning("Files API 预上传失败，judge 将回退 inline bytes：%s", path, exc_info=True)
        return None
    return f.uri


def select_pronunciation_clips(
    clips: list[AudioClip], max_n: int = MAX_PRONUNCIATION_CLIPS
) -> list[AudioClip]:
    """挑最长的 max_n 段切片（判发音的样本：长样本信息量大、省 token）。"""
    return sorted(clips, key=lambda c: c.duration_s, reverse=True)[:max_n]


def _clip_part(clip: AudioClip) -> types.Part:
    """切片 → Gemini Part：优先 Files API URI（已预上传），否则 inline bytes。

    inline 回退一次性读整个文件——本地 demo 的切片是回合 / 单题级（秒到分钟），
    可接受；生产应改流式上传 / 强制走 Files API。
    """
    if clip.file_uri:
        return types.Part.from_uri(file_uri=clip.file_uri, mime_type=AUDIO_MIME)
    return types.Part.from_bytes(data=Path(clip.path).read_bytes(), mime_type=AUDIO_MIME)


def run_judge(
    *,
    mode: str,
    transcript: Transcript,
    signals: ObjectiveSignals,
    clips: list[AudioClip] | None = None,
    sub_mode: str | None = None,
    scenario_case: str | None = None,
    case_prompt: str | None = None,
    sessions: int = 1,
    recordings: int = 1,
) -> Report:
    """跑一次 judge，返回完整 Report（judge 输出 + 系统确定性回填合并）。

    上游 5xx 按 JUDGE_RETRY_BACKOFF_S 退避重试（_generate_with_retry）；
    重试耗尽仍失败则异常上抛、pipeline 置 failed。
    """
    prompt = build_judge_prompt(
        mode,
        transcript_text=transcript.text,
        signals=asdict(signals),
        sub_mode=sub_mode,
        scenario_case=scenario_case,
        case_prompt=case_prompt,
    )

    contents: list = [prompt]
    # 雅思才喂音频（声学判发音可懂度），且只喂 2–3 段最长切片；情景只走文字诊断。
    if mode == "ielts":
        if clips:
            for clip in select_pronunciation_clips(clips):
                contents.append(_clip_part(clip))
        else:
            logger.warning(
                "run_judge: IELTS 模式未提供音频切片，Pronunciation 仅依据 transcript（降质）。"
            )

    resp = _generate_with_retry(contents)

    # 结构化解析；parsed 为空时兜底，并在失败时带上响应上下文（W2）。
    # 注意边界：解析失败（含缺 required 的 diagnostics 等 schema 违约）是**基础设施级错误**
    # （截断 / 解码失败），向上抛、由 pipeline 置 failed——不标 unscorable。
    # 系统故障不该引导用户「重录」；unscorable 仅指「judge 成功返回但拒评（dimensions=None）」。
    if resp.parsed is not None:
        judged: JudgeReport = resp.parsed
    else:
        raw = resp.text or ""
        try:
            judged = JudgeReport.model_validate_json(raw)
        except Exception as exc:
            raise RuntimeError(f"judge 响应解析失败；resp.text={raw[:200]!r}") from exc

    # —— 系统确定性组装：judge 输出 + 后端回填，LLM 碰不到这些字段 —— #
    report = Report(
        # practice_summary 用事实值，不让 LLM 猜。
        practice_summary=PracticeSummary(
            speaking_time_s=signals.speaking_time_s,
            sessions=sessions,
            recordings=recordings,
        ),
        dimensions=judged.dimensions,
        diagnostics=Diagnostics(
            **judged.diagnostics.model_dump(),
            # vocabulary_diversity_pct 就是 TTR×100：后端确定性回填（P1 收口）。
            vocabulary_diversity_pct=signals.vocabulary_diversity_pct,
        ),
    )

    if mode == "ielts" and sub_mode in (None, "exam"):
        # 方式 A（模拟考试）；sub_mode=None 视同 A（直接调用方未传时保持旧行为）。
        if report.dimensions is None:
            # judge 依 grounding 铁律拒评（静音 / 非英语 / 录音问题）——标记 unscorable，
            # 不再当硬错误抛出；保留 judge 已产出的诊断层，让用户仍有反馈而非哑失败。
            logger.info("run_judge: IELTS judge 未返回四维 dimensions，标记 unscorable。")
            report.unscorable = True
            report.unscorable_reason = UNSCORABLE_REASON
        else:
            _snap_dimension_bands(report.dimensions)    # 各维对齐 0.5 半档（W4）
            # overall_band 由系统聚合，judge 不自算。
            report.overall_band = aggregate_overall_band(report.dimensions)
    elif mode == "ielts":
        # 方式 B（module_pX）：**最终报告不出数字 band**——单 Part 样本碎，band
        # 解释力弱（IELTS.md §1/§3）。四维只是 judge 的内部诊断依据，一律剥除。
        # 可评性**只看诊断层**（不绑 dims：模型可能漏填 / 高负载降级；也可能填了
        # dims 却给空诊断）：B 用户唯一可见的就是诊断层，全空即拒评（review W1）。
        if _diagnostics_empty(report.diagnostics):
            logger.info("run_judge: 方式 B judge 未产出任何诊断内容，标记 unscorable。")
            report.unscorable = True
            report.unscorable_reason = UNSCORABLE_REASON
        report.dimensions = None
        report.overall_band = None
    else:
        # band 只在雅思有意义：情景强制无 band，且 dimensions=None 是正常、非 unscorable。
        report.dimensions = None
        report.overall_band = None
        # 情景不出改写示范（会话内 grammar_note 已即时纠正）——LLM 误填也强制清空。
        report.diagnostics.rewrites = []
        if not report.diagnostics.summary:
            # summary 是情景报告的收尾段：模型漏填只降级（前端按 null 隐藏总结段），
            # 不抛错不补写，记 warning 保留可观测性（review W1）。
            logger.warning("run_judge: 情景 judge 未产出 summary，报告将无总结段。")

    if mode == "ielts":
        # summary 仅情景对话产出（雅思已有 top_priorities 收口）——LLM 误填也剥除。
        report.diagnostics.summary = None

    return report


def _diagnostics_empty(diag: Diagnostics) -> bool:
    """诊断层是否毫无可执行反馈（方式 B 的拒评判据）。

    syntactic_analysis 是必填结构体不计；其余列表全空 = judge 没给出任何内容。
    """
    return not (
        diag.top_priorities
        or diag.frequent_errors
        or diag.fossilized_errors
        or diag.common_patterns
        or diag.self_corrections
        or diag.rewrites
    )


def _snap_dimension_bands(dims: Dimensions) -> None:
    """把各维 band 对齐到最近 0.5（IELTS 半档规范），就地修改。"""
    for d in (
        dims.fluency_coherence,
        dims.lexical_resource,
        dims.grammatical_range_accuracy,
        dims.pronunciation,
    ):
        d.band = round_to_half(d.band)
