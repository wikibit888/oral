"""judge 调用 + overall_band 聚合单测。Gemini 客户端被 mock，零网络、确定性。"""

import json

import pytest

from app.judge import run as judge_run
from app.judge.aggregate import aggregate_overall_band, round_to_half
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

WORDS = [Word("hello", 0.0, 0.5, 0.9), Word("world", 0.6, 1.0, 0.9)]
TR = Transcript(text="hello world", language="en", duration=1.0, words=WORDS)
SIG = compute_signals(WORDS, 1.0)


def _diag() -> Diagnostics:
    return Diagnostics(
        common_patterns=[], syntactic_analysis=SyntacticAnalysis(observation="o", suggestion="s"),
        frequent_errors=[], fossilized_errors=[], self_corrections=[],
        vocabulary_diversity_pct=50.0, top_priorities=[], rewrites=[],
    )


def _dim(b: float) -> Dimension:
    return Dimension(band=b, evidence=["x"], descriptor_match="m", suggestions=["s"])


def _dims(bands=(6.0, 6.5, 6.0, 7.0)) -> Dimensions:
    fc, lr, gra, pron = bands
    return Dimensions(
        fluency_coherence=_dim(fc), lexical_resource=_dim(lr),
        grammatical_range_accuracy=_dim(gra), pronunciation=_dim(pron),
    )


def _report(dimensions: Dimensions | None, overall: float | None) -> Report:
    # LLM 返回的 practice_summary 用占位值，验证 run_judge 会覆盖成事实值
    return Report(
        practice_summary=PracticeSummary(speaking_time_s=999, sessions=9, recordings=9),
        dimensions=dimensions, overall_band=overall, diagnostics=_diag(),
    )


class _FakeModels:
    def __init__(self, report, text):
        self.report = report
        self.text = text
        self.last = None

    def generate_content(self, *, model, contents, config):
        self.last = {"model": model, "contents": contents, "config": config}
        r = type("R", (), {})()
        r.parsed = self.report     # 可为 None，模拟结构化解析失败
        r.text = self.text
        return r


class _FakeClient:
    def __init__(self, report, text):
        self.models = _FakeModels(report, text)


def _patch(monkeypatch, report, text="") -> _FakeClient:
    fake = _FakeClient(report, text)
    monkeypatch.setattr(judge_run, "_client", lambda: fake)
    return fake


# —— 聚合 —— #
@pytest.mark.parametrize(
    "avg,exp",
    [(6.0, 6.0), (6.25, 6.5), (6.75, 7.0), (6.1, 6.0), (6.3, 6.5),
     (6.49, 6.5), (6.24, 6.0), (5.5, 5.5)],
)
def test_round_to_half(avg, exp):
    assert round_to_half(avg) == exp


def test_aggregate_overall_band():
    assert aggregate_overall_band(_dims()) == 6.5


# —— run_judge —— #
def test_ielts_temp0_schema_and_aggregation(monkeypatch):
    fake = _patch(monkeypatch, _report(_dims(), None))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, sub_mode="module_p2")
    cfg = fake.models.last["config"]
    assert cfg.temperature == 0
    assert cfg.response_schema is Report
    assert rep.overall_band == 6.5                       # 系统聚合
    assert rep.practice_summary.sessions == 1            # 覆盖了 LLM 的占位 9
    assert rep.practice_summary.speaking_time_s == SIG.speaking_time_s


def test_ielts_snaps_dimension_bands_to_half(monkeypatch):
    # W4：LLM 返回非半档 band，各维须对齐 0.5 再聚合
    fake = _patch(monkeypatch, _report(_dims((6.1, 6.4, 6.6, 6.9)), None))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.dimensions.fluency_coherence.band == 6.0
    assert rep.dimensions.lexical_resource.band == 6.5
    assert rep.dimensions.grammatical_range_accuracy.band == 6.5
    assert rep.dimensions.pronunciation.band == 7.0
    assert rep.overall_band == 6.5                        # snapped 均值 6.25 → 6.5


def test_ielts_includes_audio_part(monkeypatch, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFFxxxxWAVE")
    fake = _patch(monkeypatch, _report(_dims(), None))
    judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, audio_path=str(wav))
    assert len(fake.models.last["contents"]) == 2        # prompt + 音频 Part


def test_ielts_without_audio_warns_and_skips(monkeypatch, caplog):
    # W3：IELTS 无音频不报错，只 warning，且不喂音频 Part
    fake = _patch(monkeypatch, _report(_dims(), None))
    with caplog.at_level("WARNING"):
        judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, audio_path=None)
    assert len(fake.models.last["contents"]) == 1
    assert any("未提供音频" in r.message for r in caplog.records)


def test_ielts_missing_audio_file_raises(monkeypatch):
    # S3：给了路径但文件不存在 → 明确报错
    _patch(monkeypatch, _report(_dims(), None))
    with pytest.raises(FileNotFoundError):
        judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, audio_path="/no/such.wav")


def test_scenario_forces_no_band_and_no_audio(monkeypatch):
    # 即便 LLM 误填了四维与 band，情景也必须被强制清空
    fake = _patch(monkeypatch, _report(_dims(), 8.0))
    rep = judge_run.run_judge(
        mode="scenario", transcript=TR, signals=SIG,
        scenario_case="ordering", audio_path="/should/not/be/read.wav",
    )
    assert rep.dimensions is None
    assert rep.overall_band is None
    assert len(fake.models.last["contents"]) == 1        # 情景不喂音频


def test_ielts_missing_dimensions_marks_unscorable(monkeypatch):
    # 雅思 judge 拒评（dimensions=None）不再抛错：标记 unscorable，保留诊断层
    _patch(monkeypatch, _report(None, None))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.unscorable is True
    assert rep.unscorable_reason == judge_run.UNSCORABLE_REASON
    assert rep.dimensions is None
    assert rep.overall_band is None
    assert rep.diagnostics.vocabulary_diversity_pct == 50.0   # 诊断层保留


def test_ielts_scorable_is_not_unscorable(monkeypatch):
    fake = _patch(monkeypatch, _report(_dims(), None))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.unscorable is False
    assert rep.unscorable_reason is None
    assert rep.overall_band == 6.5


def test_scenario_dimensions_none_is_not_unscorable(monkeypatch):
    # 情景对话 dimensions=None 是设计上的正常态，绝不能被误标 unscorable
    _patch(monkeypatch, _report(None, None))
    rep = judge_run.run_judge(mode="scenario", transcript=TR, signals=SIG, scenario_case="ordering")
    assert rep.unscorable is False
    assert rep.unscorable_reason is None
    assert rep.dimensions is None


def test_ielts_scorable_overrides_llm_unscorable_true(monkeypatch):
    # W3：即便 LLM 在可评响应里误填 unscorable=True，系统必须强制覆盖回 False
    r = _report(_dims(), None)
    r.unscorable = True
    r.unscorable_reason = "bogus（LLM 不该填这个）"
    _patch(monkeypatch, r)
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.unscorable is False
    assert rep.unscorable_reason is None
    assert rep.overall_band == 6.5


def test_missing_diagnostics_is_infra_failure_not_unscorable(monkeypatch):
    # W1 边界：响应缺 required 的 diagnostics（schema 违约）→ 按基础设施错误抛（走 failed），
    # 不得标 unscorable——系统故障不该引导用户「重录」。
    d = json.loads(_report(None, None).model_dump_json())
    d.pop("diagnostics")
    _patch(monkeypatch, None, text=json.dumps(d))
    with pytest.raises(RuntimeError, match="judge 响应解析失败"):
        judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)


def test_parsed_none_falls_back_to_json_text(monkeypatch):
    # W2：结构化 parsed 为空时，用 resp.text 的合法 JSON 兜底
    text = _report(None, None).model_dump_json()
    _patch(monkeypatch, None, text=text)
    rep = judge_run.run_judge(mode="scenario", transcript=TR, signals=SIG, scenario_case="ordering")
    assert rep.dimensions is None
    assert rep.diagnostics.vocabulary_diversity_pct == 50.0


def test_parsed_none_and_bad_text_raises_with_context(monkeypatch):
    # W2：parsed 为空且 text 不合法 → 抛带上下文的 RuntimeError
    _patch(monkeypatch, None, text="")
    with pytest.raises(RuntimeError, match="judge 响应解析失败"):
        judge_run.run_judge(mode="scenario", transcript=TR, signals=SIG, scenario_case="ordering")


def test_empty_transcript_does_not_crash(monkeypatch):
    # S4：空 transcript / 空 words / 零时长 不应崩
    fake = _patch(monkeypatch, _report(_dims(), None))
    empty_tr = Transcript(text="", language="en", duration=0.0, words=[])
    empty_sig = compute_signals([], 0.0)
    rep = judge_run.run_judge(mode="ielts", transcript=empty_tr, signals=empty_sig)
    assert rep.overall_band == 6.5
