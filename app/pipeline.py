"""评测流水线编排（增量架构，SCHEMA §3）：报告 ≤5s 的来源。

把「课后才开始处理」改为「会话内增量消化、课后只剩一次 judge 调用」：

- `ingest_clip`：每个用户切片（实时回合 / 方式 B 单题）落地后立即在后台执行——
  whisper 转写 + Files API 预上传，产物挂 turns 行。用户继续说下一题时并行处理。
- `finalize_session`：会话结束触发——转写已全部就绪，合并词序列 → 一次信号
  计算 → 一次 judge 调用 → 报告落库。

三入口（雅思 A / 方式 B / 情景）共用，仅方式 B 不依赖 Live（PRD §3）。
状态机（SCHEMA §5.1）：live|recording → processing → completed | failed。
"""

import logging

from app import crud
from app.judge.run import run_judge, upload_clip
from app.models import AudioClip, Transcript, Word, transcript_from_json, transcript_to_json
from app.report import LiveFeedback, Report
from app.scenario_cases import judge_focus
from app.signals import ObjectiveSignals, compute_signals
from app.transcribe import transcribe

logger = logging.getLogger(__name__)


def ingest_clip(
    session_id: str,
    clip_path: str,
    *,
    role: str = "user",
    start_ts: float | None = None,
    end_ts: float | None = None,
) -> int:
    """增量消化一个切片：转写（词级时间戳）+ Files API 预上传，产物挂 turns 行。

    同步函数：会话内逐切片由 BackgroundTasks / 线程池执行（whisper 是 CPU 阻塞活），
    与对话互不阻塞。预上传失败只降级（file_uri=NULL，judge 回退 inline bytes），
    不让会话失败。返回 turn id。
    """
    if crud.get_session(session_id) is None:
        raise ValueError(f"session 不存在: {session_id}")

    turn_id = crud.create_turn(
        session_id=session_id, role=role, clip_path=clip_path,
        start_ts=start_ts, end_ts=end_ts,
    )
    transcript = transcribe(clip_path)
    file_uri = upload_clip(clip_path)
    crud.finish_turn(
        turn_id,
        text=transcript.text,
        transcript_json=transcript_to_json(transcript),
        file_uri=file_uri,
    )
    return turn_id


def finalize_session(
    session_id: str, *, sessions: int = 1, live_feedback: LiveFeedback | None = None
) -> None:
    """会话结束的收口：合并已就绪的切片转写 → 一次信号计算 → 一次 judge → 报告落库。

    增量流水线保证走到这里时转写 / 预上传已全部完成，唯一剩余耗时 = 一次 judge
    调用（flash 级 + 结构化输出）→ 报告 ≤5s 可见。
    任一环节异常 → status=failed 并向上抛（日志留痕），不写半份报告。
    live_feedback：情景 live 会话的 FC 反馈实录（live_ws 收口时从应答台取走传入）；
    方式 B / 雅思调用方不传，run_judge 内另有模式守门。
    """
    session = crud.get_session(session_id)
    if session is None:
        raise ValueError(f"session 不存在: {session_id}")

    # 双调用方：sessions review 入口已先行翻 processing（前端即刻轮询），此处
    # 重复置位无害；Live 路径（end_session 回调）则依赖这一行进入 processing。
    crud.update_session_status(session_id, "processing")
    try:
        rows = crud.list_processed_user_turns(session_id)
        if not rows:
            raise ValueError(f"session 无已转写的用户切片，无法评测: {session_id}")

        transcripts = [transcript_from_json(r["transcript_json"]) for r in rows]
        merged = merge_transcripts(transcripts)
        signals = compute_signals(merged.words, merged.duration)
        # duration_s 取 whisper 转写时长（TEST.md H1：可能略低估实际录音时长），
        # 仅用于「挑最长切片」的相对排序，系统性偏差不影响选择正确性。
        clips = [
            AudioClip(path=r["clip_path"], duration_s=tr.duration, file_uri=r["file_uri"])
            for r, tr in zip(rows, transcripts)
        ]
        report = run_judge(
            mode=session["mode"],
            transcript=merged,
            signals=signals,
            clips=clips,
            sub_mode=session["sub_mode"],
            scenario_case=session["scenario_case"],
            # 情景 case 侧重段（注册表查得；非情景 / 未知 case 为 None，prompt 层降级占位）
            case_prompt=judge_focus(session["scenario_case"]),
            live_feedback=live_feedback,
            sessions=sessions,
            recordings=len(rows),
        )
        _persist_report(session_id, session["mode"], report, signals)
    except Exception:
        crud.update_session_status(session_id, "failed")
        logger.exception("评测流水线 finalize 失败: session=%s", session_id)
        raise
    else:
        # 报告落库成功才置 completed（SCHEMA §5.1 枚举）。单独放 else：若它本身
        # DB 出错，异常上抛、状态停在 processing，绝不把已落库的完整报告误标
        # failed 被 GET /reports 屏蔽。
        crud.update_session_status(session_id, "completed")


def merge_transcripts(transcripts: list[Transcript]) -> Transcript:
    """把多段切片转写拼成一条会话级词序列（信号计算的输入）。

    第 i 段整体平移 Σ_{j<i} duration_j：各切片内部的停顿原样保留；切片衔接处的
    gap = 前段尾部静默 + 后段起始静默——都发生在用户自己的说话窗口内（考官说话
    时段不在任何切片里），是真实犹豫信号，不是拼接伪影。总时长 = 各切片时长之和
    （即用户说话窗口总长，gross_wpm 的分母）。
    """
    words: list[Word] = []
    texts: list[str] = []
    offset = 0.0
    language = transcripts[0].language if transcripts else "en"
    for tr in transcripts:
        if tr.text:
            texts.append(tr.text)
        for w in tr.words:
            words.append(
                Word(
                    word=w.word,
                    start=round(w.start + offset, 3),
                    end=round(w.end + offset, 3),
                    probability=w.probability,
                )
            )
        offset = round(offset + tr.duration, 3)
    return Transcript(
        text=" ".join(texts).strip(), language=language, duration=offset, words=words
    )


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
        error_rate=_error_rate(report, signals),
        report_json=report.model_dump_json(),
    )


def _error_rate(report: Report, signals: ObjectiveSignals) -> float | None:
    """error_rate = judge frequent_errors 总次数 / 转写词数 ×100（每百词，SCHEMA §5.1）。

    judge 计数有漂移（LLM 产出），故只作参考列；无词数（空转写）时为 NULL。
    """
    if signals.word_count <= 0:
        return None
    total = sum(e.count for e in report.diagnostics.frequent_errors)
    return round(total / signals.word_count * 100, 2)
