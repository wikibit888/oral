"""课后报告流水线编排：把已落库的录音串成完整报告并落库。

已上传 session → whisper 转写 → 客观信号 → 结构化 judge → 完整报告 → reports 落库。
三入口（雅思方式 B / 情景对话）共用，**不依赖 Live**（PRD §3、§10 第 8h 关卡）。
诊断层由 judge 一次产出，本模块只负责正确串联、聚合落库、状态机推进。

状态机：uploaded → processing → done | failed。
"""

import logging

from app import crud
from app.judge.run import run_judge
from app.report import Report
from app.signals import ObjectiveSignals, compute_signals
from app.transcribe import transcribe

logger = logging.getLogger(__name__)


def process_session(session_id: str) -> None:
    """对一条已上传会话跑完整课后流水线，结果落 reports 表。

    同步函数：由 FastAPI BackgroundTasks 丢到线程池执行（whisper 是 CPU 阻塞活），
    不阻塞事件循环。任一环节异常 → status=failed 并向上抛（日志留痕），不写半份报告。
    """
    session = crud.get_session(session_id)
    if session is None:
        raise ValueError(f"session 不存在: {session_id}")
    if not session["audio_path"]:
        raise ValueError(f"session 无音频，无法处理: {session_id}")

    crud.update_session_status(session_id, "processing")
    try:
        transcript = transcribe(session["audio_path"])
        # 时长以 WAV 头为准（上传时落库的 duration_s）；缺省回退转写时长。
        duration_s = (
            session["duration_s"]
            if session["duration_s"] is not None
            else transcript.duration
        )
        signals = compute_signals(transcript.words, duration_s)
        report = run_judge(
            mode=session["mode"],
            transcript=transcript,
            signals=signals,
            audio_path=session["audio_path"],
            sub_mode=session["sub_mode"],
            scenario_case=session["scenario_case"],
        )
        _persist_report(session_id, session["mode"], report, signals)
    except Exception:
        crud.update_session_status(session_id, "failed")
        logger.exception("课后流水线失败: session=%s", session_id)
        raise
    else:
        # 报告落库成功才置 done。置 done 单独放 else：若它本身 DB 出错，异常上抛、
        # 状态停在 processing，绝不把已落库的完整报告误标 failed 被 GET /reports 屏蔽。
        crud.update_session_status(session_id, "done")


def _persist_report(
    session_id: str, mode: str, report: Report, signals: ObjectiveSignals
) -> None:
    """从 Report + 客观信号抽正规化列，连同完整 report_json 落 reports 表。

    band 只在雅思有意义：情景对话四维列全 NULL。通用流利度列取纯客观信号
    （零 LLM、零漂移，供跨会话曲线）。
    """
    dims = report.dimensions
    crud.create_report(
        session_id=session_id,
        mode=mode,
        overall_band=report.overall_band,
        fc_band=dims.fluency_coherence.band if dims is not None else None,
        lr_band=dims.lexical_resource.band if dims is not None else None,
        gra_band=dims.grammatical_range_accuracy.band if dims is not None else None,
        pron_band=dims.pronunciation.band if dims is not None else None,
        # 注意 TEST.md H1：whisper 词级时间戳系统性低估停顿，故 silence_ratio 偏小、
        # gross_wpm（含静默）偏大。待停顿检测改进前，这两列进趋势线应视作有已知偏差。
        wpm=signals.gross_wpm,
        silence_ratio=signals.pauses.silence_ratio,
        filler_pm=signals.filler_per_min,
        ttr=signals.type_token_ratio,
        # error_rate 无确定性客观来源——judge 的错误计数会漂移、按 PRD §8.2 不进趋势线，故留空。
        error_rate=None,
        report_json=report.model_dump_json(),
    )
