"""课后流水线编排 + 落库单测。

transcribe / run_judge 被 mock（零网络、不下载 whisper 权重），只验证：
串联顺序、正规化列抽取、状态机推进、失败不写半份报告。DB 用临时文件隔离。
"""

import pytest

from app import crud, db, pipeline
from app.config import settings
from app.models import Transcript, Word
from app.report import (
    Diagnostics,
    Dimension,
    Dimensions,
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


def _diag() -> Diagnostics:
    return Diagnostics(
        common_patterns=[], syntactic_analysis=SyntacticAnalysis(observation="o", suggestion="s"),
        frequent_errors=[], fossilized_errors=[], self_corrections=[],
        vocabulary_diversity_pct=80.0, top_priorities=[], rewrites=[],
    )


def _dim(b: float) -> Dimension:
    return Dimension(band=b, evidence=["x"], descriptor_match="m", suggestions=["s"])


def _ielts_report() -> Report:
    dims = Dimensions(
        fluency_coherence=_dim(6.0), lexical_resource=_dim(6.5),
        grammatical_range_accuracy=_dim(6.0), pronunciation=_dim(7.0),
    )
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=0, sessions=1, recordings=1),
        dimensions=dims, overall_band=6.5, diagnostics=_diag(),
    )


def _scenario_report() -> Report:
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=0, sessions=1, recordings=1),
        dimensions=None, overall_band=None, diagnostics=_diag(),
    )


def _seed_session(mode, sub_mode=None, scenario_case=None, audio_path="/fake.wav", status="uploaded"):
    crud.create_session(
        session_id="s1", mode=mode, sub_mode=sub_mode, scenario_case=scenario_case,
        audio_path=audio_path, duration_s=DURATION, status=status,
    )


def _patch_stages(monkeypatch, report):
    """把 transcribe / run_judge 换成 canned 实现，捕获 run_judge 收到的 kwargs。"""
    captured = {}
    monkeypatch.setattr(pipeline, "transcribe", lambda path: TR)

    def fake_run_judge(**kw):
        captured.update(kw)
        return report

    monkeypatch.setattr(pipeline, "run_judge", fake_run_judge)
    return captured


def test_ielts_pipeline_persists_normalized_columns(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p2")
    captured = _patch_stages(monkeypatch, _ielts_report())

    pipeline.process_session("s1")

    # 状态推进到 done
    assert crud.get_session("s1")["status"] == "done"

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
    assert row["error_rate"] is None              # 无确定性来源，留空

    # 完整报告 JSON 可往返
    rep = Report.model_validate_json(row["report_json"])
    assert rep.dimensions is not None
    assert rep.diagnostics.vocabulary_diversity_pct == 80.0


def test_pipeline_passes_session_fields_to_judge(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p3")
    captured = _patch_stages(monkeypatch, _ielts_report())

    pipeline.process_session("s1")

    # judge 收到会话上下文 + 用 WAV 头时长复算的信号
    assert captured["mode"] == "ielts"
    assert captured["sub_mode"] == "module_p3"
    assert captured["audio_path"] == "/fake.wav"
    assert captured["signals"].duration_s == DURATION


def test_scenario_pipeline_leaves_band_columns_null(tmp_db, monkeypatch):
    _seed_session("scenario", scenario_case="ordering")
    _patch_stages(monkeypatch, _scenario_report())

    pipeline.process_session("s1")

    row = crud.get_report("s1")
    assert row["mode"] == "scenario"
    assert row["overall_band"] is None
    assert row["fc_band"] is None and row["pron_band"] is None
    # 但通用流利度列照常有值（情景也喂趋势线）
    assert row["wpm"] is not None


def test_pipeline_failure_marks_failed_and_writes_no_report(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p1")

    def boom(path):
        raise RuntimeError("whisper 挂了")

    monkeypatch.setattr(pipeline, "transcribe", boom)

    with pytest.raises(RuntimeError, match="whisper 挂了"):
        pipeline.process_session("s1")

    assert crud.get_session("s1")["status"] == "failed"
    assert crud.get_report("s1") is None          # 不留半份报告


def test_pipeline_missing_session_raises(tmp_db):
    with pytest.raises(ValueError, match="不存在"):
        pipeline.process_session("nope")


def test_pipeline_missing_audio_raises_before_processing(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p1", audio_path=None)
    _patch_stages(monkeypatch, _ielts_report())

    with pytest.raises(ValueError, match="无音频"):
        pipeline.process_session("s1")
    # 没音频在置 processing 前就拦下，状态不变
    assert crud.get_session("s1")["status"] == "uploaded"


def test_pipeline_reprocess_is_idempotent(tmp_db, monkeypatch):
    _seed_session("ielts", sub_mode="module_p2")
    _patch_stages(monkeypatch, _ielts_report())

    pipeline.process_session("s1")
    pipeline.process_session("s1")                 # 重跑不报错、不重复行

    assert crud.get_session("s1")["status"] == "done"   # 第二次也正常收尾到 done
    with db.get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM reports WHERE session_id = ?", ("s1",)).fetchone()["n"]
    assert n == 1
