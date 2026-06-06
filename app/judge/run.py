"""结构化 judge 调用：一次 Gemini 调用产出整份报告。

护城河铁律落地：
- temperature=0 + 结构化输出（response_schema=Report）；
- 雅思额外喂音频切片，让模型听发音判可懂度；情景只走文字诊断；
- overall_band 由系统按四维确定性聚合（judge 不自算；信号≠成绩）；
- band 只在雅思：情景强制 dimensions / overall_band 为 None；
- 雅思 judge 拒评（dimensions=None）标记 unscorable 而非抛错，保留诊断层、不哑失败。
"""

import logging
from dataclasses import asdict
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings
from app.judge.aggregate import aggregate_overall_band, round_to_half
from app.judge.prompt import build_judge_prompt
from app.models import Transcript
from app.report import Dimensions, PracticeSummary, Report
from app.signals import ObjectiveSignals

logger = logging.getLogger(__name__)

# 雅思拒评时给用户的统一说明（系统设置，不让 LLM 自由发挥）。
UNSCORABLE_REASON = "无法评分：未检出可评的英语口语内容（可能是静音、非英语或录音问题），请重录后再试。"

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


def run_judge(
    *,
    mode: str,
    transcript: Transcript,
    signals: ObjectiveSignals,
    audio_path: str | None = None,
    sub_mode: str | None = None,
    scenario_case: str | None = None,
    case_prompt: str | None = None,
    sessions: int = 1,
    recordings: int = 1,
) -> Report:
    """跑一次 judge，返回完整 Report。"""
    prompt = build_judge_prompt(
        mode,
        transcript_text=transcript.text,
        signals=asdict(signals),
        sub_mode=sub_mode,
        scenario_case=scenario_case,
        case_prompt=case_prompt,
    )

    contents: list = [prompt]
    # 雅思才喂音频（声学判发音可懂度）；情景只走文字诊断。
    if mode == "ielts":
        if audio_path:
            contents.append(
                types.Part.from_bytes(
                    data=Path(audio_path).read_bytes(), mime_type="audio/wav"
                )
            )
        else:
            logger.warning(
                "run_judge: IELTS 模式未提供音频，Pronunciation 仅依据 transcript（降质）。"
            )

    resp = _client().models.generate_content(
        model=settings.judge_model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=Report,
        ),
    )

    # 结构化解析；parsed 为空时兜底，并在失败时带上响应上下文（W2）。
    # 注意边界：解析失败（含缺 required 的 diagnostics 等 schema 违约）是**基础设施级错误**
    # （截断 / 解码失败），向上抛、由 pipeline 置 failed——不标 unscorable。
    # 系统故障不该引导用户「重录」；unscorable 仅指「judge 成功返回但拒评（dimensions=None）」。
    if resp.parsed is not None:
        report: Report = resp.parsed
    else:
        raw = resp.text or ""
        try:
            report = Report.model_validate_json(raw)
        except Exception as exc:
            raise RuntimeError(f"judge 响应解析失败；resp.text={raw[:200]!r}") from exc

    # —— 确定性后处理 —— #
    # practice_summary 用事实值，不让 LLM 猜。
    report.practice_summary = PracticeSummary(
        speaking_time_s=signals.speaking_time_s,
        sessions=sessions,
        recordings=recordings,
    )
    if mode == "ielts":
        if report.dimensions is None:
            # judge 依 grounding 铁律拒评（静音 / 非英语 / 录音问题）——标记 unscorable，
            # 不再当硬错误抛出；保留 judge 已产出的诊断层，让用户仍有反馈而非哑失败。
            logger.info("run_judge: IELTS judge 未返回四维 dimensions，标记 unscorable。")
            report.overall_band = None
            report.unscorable = True
            report.unscorable_reason = UNSCORABLE_REASON
        else:
            _snap_dimension_bands(report.dimensions)    # 各维对齐 0.5 半档（W4）
            # overall_band 由系统聚合，judge 不自算。
            report.overall_band = aggregate_overall_band(report.dimensions)
            report.unscorable = False
            report.unscorable_reason = None
    else:
        # band 只在雅思有意义：情景强制无 band，且 dimensions=None 是正常、非 unscorable。
        report.dimensions = None
        report.overall_band = None
        report.unscorable = False
        report.unscorable_reason = None

    return report


def _snap_dimension_bands(dims: Dimensions) -> None:
    """把各维 band 对齐到最近 0.5（IELTS 半档规范），就地修改。"""
    for d in (
        dims.fluency_coherence,
        dims.lexical_resource,
        dims.grammatical_range_accuracy,
        dims.pronunciation,
    ):
        d.band = round_to_half(d.band)
