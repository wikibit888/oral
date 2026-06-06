"""评测流水线（增量架构）编排 + 落库单测。

transcribe / run_judge / upload_clip 被 mock（零网络、不下载 whisper 权重），只验证：
增量串联（ingest_clip → finalize_session）、合并逻辑、正规化列抽取（含 error_rate）、
状态机推进、失败不写半份报告。DB 用临时文件隔离。
"""

import pytest

from app import crud, db, pipeline
from app.config import settings
from app.models import Transcript, Word, transcript_from_json
from app.report import (
    Diagnostics,
    Dimension,
    Dimensions,
    FrequentError,
    PracticeSummary,
    Report,
    SyntacticAnalysis,
)
from app.signals import compute_signals

# 固定一段词级时间戳，信号可确定性复算
WORDS = [
    Word("i", 0.0, 0.2, 0.9),
    Word("think", 0.2, 0.6, 0.9),
    Word("science", 0.6, 1.1, 0.9),
    Word("is", 1.1, 1.3, 0.9),
    Word("curiosity", 2.5, 3.4, 0.9),   # 与上一词间隔 1.2s → 犹豫停顿
]
TR = Transcript(text="i think science is curiosity", language="en", duration=4.0, words=WORDS)
DURATION = 4.0


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """每个测试用独立临时 SQLite 文件，建表后交还。"""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    db.init_db()
    yield


def _diag(frequent_errors=()) -> Diagnostics:
    return Diagnostics(
        common_patterns=[], syntactic_analysis=SyntacticAnalysis(observation="o", suggestion="s"),
        frequent_errors=list(frequent_errors), fossilized_errors=[], self_corrections=[],
        vocabulary_diversity_pct=80.0, top_priorities=[], rewrites=[],
    )


def _dim(b: float) -> Dimension:
    return Dimension(band=b, evidence=["x"], descriptor_match="m", suggestions=["s"])


def _ielts_report(frequent_errors=()) -> Report:
    dims = Dimensions(
        fluency_coherence=_dim(6.0), lexical_resource=_dim(6.5),
        grammatical_range_accuracy=_dim(6.0), pronunciation=_dim(7.0),
    )
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=0, sessions=1, recordings=1),
        dimensions=dims, overall_band=6.5, diagnostics=_diag(frequent_errors),
    )


def _scenario_report() -> Report:
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=0, sessions=1, recordings=1),
        dimensions=None, overall_band=None, diagnostics=_diag(),
    )


def _unscorable_report() -> Report:
    # 模拟 run_judge 对不可评雅思输入返回的报告（无 band、标记 unscorable、诊断层仍在）
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=0, sessions=1, recordings=1),
        dimensions=None, overall_band=None,
        unscorable=True, unscorable_reason="无法评分：请重录后再试。",
        diagnostics=_diag(),
    )


def _seed_session(mode, sub_mode=None, scenario_case=None, audio_path="/fake.wav", status="recording"):
    crud.create_session(
        session_id="s1", mode=mode, sub_mode=sub_mode, scenario_case=scenario_case,
        audio_path=audio_path, duration_s=DURATION, status=status,
    )


def _patch_stages(monkeypatch, report, file_uri=None, transcript=TR):
    """把 transcribe / upload_clip / run_judge 换成 canned 实现，捕获 run_judge kwargs。"""
    captured = {}
    monkeypatch.setattr(pipeline, "transcribe", lambda path: transcript)
    monkeypatch.setattr(pipeline, "upload_clip", lambda path: file_uri)

    def fake_run_judge(**kw):
        captured.update(kw)
        return report

    monkeypatch.setattr(pipeline, "run_judge", fake_run_judge)
    return captured


# —— 单切片全链路（ingest → finalize，方式 B 单题等价路径）—— #
def _ingest_and_finalize(session_id="s1", clip="/fake.wav"):
    pipeline.ingest_clip(session_id, clip)
    pipeline.finalize_session(session_id)

def test_ielts_pipeline_persists_normalized_columns(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p2")
    _patch_stages(monkeypatch, _ielts_report())

    _ingest_and_finalize()

    # 状态推进到 completed
    assert crud.get_session("s1")["status"] == "completed"

    row = crud.get_report("s1")
    assert row is not None
    # 雅思四维 + overall 落正规化列
    assert row["overall_band"] == 6.5
    assert (row["fc_band"], row["lr_band"], row["gra_band"], row["pron_band"]) == (6.0, 6.5, 6.0, 7.0)

    # 通用流利度列取确定性客观信号（非 LLM）
    sig = compute_signals(WORDS, DURATION)
    assert row["wpm"] == sig.gross_wpm
    assert row["silence_ratio"] == sig.pauses.silence_ratio
    assert row["filler_pm"] == sig.filler_per_min
    assert row["ttr"] == sig.type_token_ratio
    assert row["error_rate"] == 0.0               # 无 frequent_errors → 0 每百词

    # 完整报告 JSON 可往返
    rep = Report.model_validate_json(row["report_json"])
    assert rep.dimensions is not None
    assert rep.diagnostics.vocabulary_diversity_pct == 80.0


def test_error_rate_persisted_per_100_words(tmp_db, monkeypatch):
    # error_rate = frequent_errors 总次数 / 转写词数 ×100：(2+1)/5×100 = 60.0
    _seed_session("ielts", sub_mode="module_p1")
    errors = [
        FrequentError(category="grammar", desc="三单一致", count=2),
        FrequentError(category="vocabulary", desc="搭配", count=1),
    ]
    _patch_stages(monkeypatch, _ielts_report(frequent_errors=errors))

    _ingest_and_finalize()

    assert crud.get_report("s1")["error_rate"] == 60.0


def test_pipeline_passes_session_fields_and_clips_to_judge(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p3")
    captured = _patch_stages(monkeypatch, _ielts_report(), file_uri="files/abc")

    _ingest_and_finalize()

    # judge 收到会话上下文 + 切片引用（含预上传 URI）+ 合并信号
    assert captured["mode"] == "ielts"
    assert captured["sub_mode"] == "module_p3"
    assert captured["signals"].duration_s == DURATION
    clips = captured["clips"]
    assert len(clips) == 1
    assert clips[0].path == "/fake.wav"
    assert clips[0].file_uri == "files/abc"
    assert clips[0].duration_s == DURATION
    assert captured["recordings"] == 1


def test_scenario_pipeline_leaves_band_columns_null(tmp_db, monkeypatch):
    _seed_session("scenario", scenario_case="ordering")
    _patch_stages(monkeypatch, _scenario_report())

    _ingest_and_finalize()

    row = crud.get_report("s1")
    assert row["mode"] == "scenario"
    assert row["overall_band"] is None
    assert row["fc_band"] is None and row["pron_band"] is None
    # 但通用流利度列照常有值（情景也喂趋势线）
    assert row["wpm"] is not None


def test_unscorable_ielts_persists_done_with_flag(tmp_db, monkeypatch):
    # 不可评雅思输入不再哑失败：status=completed、band 列 NULL、报告带 unscorable + 诊断层
    _seed_session("ielts", sub_mode="module_p2")
    _patch_stages(monkeypatch, _unscorable_report())

    _ingest_and_finalize()

    assert crud.get_session("s1")["status"] == "completed"     # 不是 failed
    row = crud.get_report("s1")
    assert row is not None
    assert row["overall_band"] is None
    assert (row["fc_band"], row["pron_band"]) == (None, None)
    rep = Report.model_validate_json(row["report_json"])
    assert rep.unscorable is True
    assert rep.unscorable_reason is not None
    assert rep.diagnostics.vocabulary_diversity_pct == 80.0   # 诊断层保留可读


def test_reupload_same_clip_dedupes_to_latest(tmp_db, monkeypatch):
    # review W4：方式 B 同题重录 = 同 clip_path 再次 ingest——finalize 只取
    # 最新一次转写，词序列/信号不翻倍
    _seed_session("ielts", sub_mode="module_p2")
    captured = _patch_stages(monkeypatch, _ielts_report())

    pipeline.ingest_clip("s1", "/fake.wav")
    pipeline.ingest_clip("s1", "/fake.wav")   # 重录同一题
    pipeline.finalize_session("s1")

    assert captured["recordings"] == 1                     # 去重后只算一份
    assert captured["signals"].word_count == len(WORDS)    # 词数不翻倍


def test_pipeline_failure_marks_failed_and_writes_no_report(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p1")
    monkeypatch.setattr(pipeline, "upload_clip", lambda path: None)

    def boom(path):
        raise RuntimeError("whisper 挂了")

    monkeypatch.setattr(pipeline, "transcribe", boom)

    with pytest.raises(RuntimeError, match="whisper 挂了"):
        pipeline.ingest_clip("s1", "/fake.wav")
    # ingest 炸了不碰状态（API 层吞日志）；review 后 finalize 无已转写切片 → failed
    with pytest.raises(ValueError, match="无已转写"):
        pipeline.finalize_session("s1")
    assert crud.get_session("s1")["status"] == "failed"
    assert crud.get_report("s1") is None          # 不留半份报告


def test_judge_failure_in_finalize_marks_failed_no_report(tmp_db, monkeypatch):
    # review 补漏：ingest 成功、finalize 阶段 run_judge 失败——走的是 finalize_session
    # 自己的 except，仍须 failed + 不写半份报告。
    _seed_session("ielts", sub_mode="module_p1")
    monkeypatch.setattr(pipeline, "transcribe", lambda path: TR)
    monkeypatch.setattr(pipeline, "upload_clip", lambda path: None)

    def judge_boom(**kw):
        raise RuntimeError("judge 挂了")

    monkeypatch.setattr(pipeline, "run_judge", judge_boom)

    pipeline.ingest_clip("s1", "/fake.wav")
    with pytest.raises(RuntimeError, match="judge 挂了"):
        pipeline.finalize_session("s1")

    assert crud.get_session("s1")["status"] == "failed"
    assert crud.get_report("s1") is None


def test_pipeline_missing_session_raises(tmp_db):
    with pytest.raises(ValueError, match="不存在"):
        pipeline.ingest_clip("nope", "/fake.wav")
    with pytest.raises(ValueError, match="不存在"):
        pipeline.finalize_session("nope")


def test_pipeline_reprocess_is_idempotent(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p2")
    captured = _patch_stages(monkeypatch, _ielts_report())

    pipeline.ingest_clip("s1", "/fake.wav")
    pipeline.finalize_session("s1")
    pipeline.finalize_session("s1")        # finalize 重跑不报错、不重复报告行

    assert crud.get_session("s1")["status"] == "completed"   # 第二次也正常收尾到 completed
    with db.get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM reports WHERE session_id = ?", ("s1",)).fetchone()["n"]
        t = conn.execute("SELECT COUNT(*) AS n FROM turns WHERE session_id = ?", ("s1",)).fetchone()["n"]
    assert n == 1
    assert t == 1                                  # ingest 只跑一次 → 单 turn；finalize 重跑不增行
    assert len(captured["clips"]) == 1


# —— 增量入口：ingest_clip + finalize_session —— #
def _clip_tr(text: str, words: list[Word], duration: float) -> Transcript:
    return Transcript(text=text, language="en", duration=duration, words=words)


CLIP1 = _clip_tr("i think", [Word("i", 0.0, 0.2, 0.9), Word("think", 0.2, 0.6, 0.9)], 1.0)
CLIP2 = _clip_tr(
    "science is curiosity",
    [Word("science", 0.1, 0.6, 0.9), Word("is", 0.6, 0.8, 0.9), Word("curiosity", 2.0, 2.9, 0.9)],
    3.0,
)


def test_ingest_clip_persists_turn_with_transcript_and_uri(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p2", audio_path=None)
    monkeypatch.setattr(pipeline, "transcribe", lambda path: CLIP1)
    monkeypatch.setattr(pipeline, "upload_clip", lambda path: "files/u1")

    turn_id = pipeline.ingest_clip("s1", "/clip1.wav", start_ts=10.0, end_ts=11.0)

    rows = crud.list_processed_user_turns("s1")
    assert [r["id"] for r in rows] == [turn_id]
    row = rows[0]
    assert row["text"] == "i think"
    assert row["file_uri"] == "files/u1"
    assert row["clip_path"] == "/clip1.wav"
    assert (row["start_ts"], row["end_ts"]) == (10.0, 11.0)
    restored = transcript_from_json(row["transcript_json"])
    assert restored == CLIP1                       # 词时间戳无损往返


def test_ingest_clip_missing_session_raises(tmp_db, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe", lambda path: CLIP1)
    monkeypatch.setattr(pipeline, "upload_clip", lambda path: None)
    with pytest.raises(ValueError, match="不存在"):
        pipeline.ingest_clip("nope", "/clip.wav")


def test_incremental_two_clips_then_finalize(tmp_db, monkeypatch):
    """逐题 ingest 两段切片 → finalize 只剩一次 judge：信号按合并词序列计算。"""
    _seed_session("ielts", sub_mode="module_p2", audio_path=None)
    transcripts = iter([CLIP1, CLIP2])
    monkeypatch.setattr(pipeline, "transcribe", lambda path: next(transcripts))
    monkeypatch.setattr(pipeline, "upload_clip", lambda path: None)
    captured = {}

    def fake_run_judge(**kw):
        captured.update(kw)
        return _ielts_report()

    monkeypatch.setattr(pipeline, "run_judge", fake_run_judge)

    pipeline.ingest_clip("s1", "/clip1.wav")
    pipeline.ingest_clip("s1", "/clip2.wav")
    pipeline.finalize_session("s1")

    assert crud.get_session("s1")["status"] == "completed"
    # judge 收到合并 transcript + 按合并词序列复算的信号 + 两段切片引用
    merged = pipeline.merge_transcripts([CLIP1, CLIP2])
    assert captured["transcript"].text == "i think science is curiosity"
    assert captured["signals"] == compute_signals(merged.words, merged.duration)
    assert [c.path for c in captured["clips"]] == ["/clip1.wav", "/clip2.wav"]
    assert captured["recordings"] == 2
    # 正规化列与报告落库
    row = crud.get_report("s1")
    assert row is not None
    assert row["wpm"] == compute_signals(merged.words, merged.duration).gross_wpm


def test_finalize_without_processed_turns_fails(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p2", audio_path=None)
    with pytest.raises(ValueError, match="无已转写的用户切片"):
        pipeline.finalize_session("s1")
    assert crud.get_session("s1")["status"] == "failed"


# —— merge_transcripts —— #
def test_merge_transcripts_offsets_and_duration():
    merged = pipeline.merge_transcripts([CLIP1, CLIP2])
    assert merged.duration == 4.0                  # Σ 切片时长
    assert merged.text == "i think science is curiosity"
    # 第二段整体平移 1.0（CLIP1 的 duration）
    assert [round(w.start, 3) for w in merged.words] == [0.0, 0.2, 1.1, 1.6, 3.0]
    # 切片内部停顿保留：CLIP2 内 is(0.8)→curiosity(2.0) 的 1.2s 犹豫平移后仍是 1.2s
    assert round(merged.words[4].start - merged.words[3].end, 3) == 1.2


def test_merge_transcripts_boundary_gap_is_real_user_silence():
    # 衔接处 gap = 前段尾部静默(1.0-0.6=0.4) + 后段起始静默(0.1) = 0.5 —— 计入停顿
    merged = pipeline.merge_transcripts([CLIP1, CLIP2])
    sig = compute_signals(merged.words, merged.duration)
    assert sig.pauses.silence_count == 2           # 边界 0.5s + CLIP2 内 1.2s
    assert sig.pauses.hesitation_count == 1        # 仅 1.2s 达犹豫阈值


def test_merge_transcripts_single_clip_is_identity():
    merged = pipeline.merge_transcripts([TR])
    assert merged == TR


def test_merge_transcripts_empty_list():
    merged = pipeline.merge_transcripts([])
    assert merged.words == []
    assert merged.text == ""
    assert merged.duration == 0.0
