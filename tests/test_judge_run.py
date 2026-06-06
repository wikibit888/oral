"""judge 调用 + overall_band 聚合单测。Gemini 客户端被 mock，零网络、确定性。

P1 收口后：judge 结构化输出是 JudgeReport（只含 dimensions + 诊断层）；
practice_summary / overall_band / unscorable* / vocabulary_diversity_pct
全部由 run_judge 内系统确定性设置或回填。
"""

import json

import pytest

from app.judge import run as judge_run
from app.judge.aggregate import aggregate_overall_band, round_to_half
from app.models import AudioClip, Transcript, Word
from app.report import (
    Diagnostics,
    Dimension,
    Dimensions,
    JudgeDiagnostics,
    JudgeReport,
    Report,
    SyntacticAnalysis,
)
from app.signals import compute_signals

WORDS = [Word("hello", 0.0, 0.5, 0.9), Word("world", 0.6, 1.0, 0.9)]
TR = Transcript(text="hello world", language="en", duration=1.0, words=WORDS)
SIG = compute_signals(WORDS, 1.0)


def _diag() -> JudgeDiagnostics:
    return JudgeDiagnostics(
        common_patterns=[], syntactic_analysis=SyntacticAnalysis(observation="o", suggestion="s"),
        frequent_errors=[], fossilized_errors=[], self_corrections=[],
        top_priorities=[], rewrites=[],
    )


def _dim(b: float) -> Dimension:
    return Dimension(band=b, evidence=["x"], descriptor_match="m", suggestions=["s"])


def _dims(bands=(6.0, 6.5, 6.0, 7.0)) -> Dimensions:
    fc, lr, gra, pron = bands
    return Dimensions(
        fluency_coherence=_dim(fc), lexical_resource=_dim(lr),
        grammatical_range_accuracy=_dim(gra), pronunciation=_dim(pron),
    )


def _judged(dimensions: Dimensions | None) -> JudgeReport:
    return JudgeReport(dimensions=dimensions, diagnostics=_diag())


class _FakeModels:
    def __init__(self, judged, text):
        self.judged = judged
        self.text = text
        self.last = None

    def generate_content(self, *, model, contents, config):
        self.last = {"model": model, "contents": contents, "config": config}
        r = type("R", (), {})()
        r.parsed = self.judged     # 可为 None，模拟结构化解析失败
        r.text = self.text
        return r


class _FakeClient:
    def __init__(self, judged, text):
        self.models = _FakeModels(judged, text)


def _patch(monkeypatch, judged, text="") -> _FakeClient:
    fake = _FakeClient(judged, text)
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


# —— schema 收口（P1）—— #
def test_judge_schema_excludes_backfilled_fields():
    # judge 结构化 schema 不含系统回填字段——LLM 想填也没地方填
    assert "vocabulary_diversity_pct" not in JudgeDiagnostics.model_fields
    assert set(JudgeReport.model_fields) == {"dimensions", "diagnostics"}
    # 对外 Report shape 不变：完整诊断层仍带 vocabulary_diversity_pct
    assert "vocabulary_diversity_pct" in Diagnostics.model_fields


# —— run_judge —— #
def test_ielts_temp0_schema_and_aggregation(monkeypatch):
    fake = _patch(monkeypatch, _judged(_dims()))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, sub_mode="module_p2")
    cfg = fake.models.last["config"]
    assert cfg.temperature == 0
    assert cfg.response_schema is JudgeReport
    assert isinstance(rep, Report)
    assert rep.overall_band == 6.5                       # 系统聚合
    assert rep.practice_summary.sessions == 1            # 系统事实值，非 LLM 产出
    assert rep.practice_summary.speaking_time_s == SIG.speaking_time_s


def test_vocabulary_diversity_backfilled_from_signals(monkeypatch):
    # P1 收口：vocabulary_diversity_pct = 客观信号 TTR×100，由后端回填
    _patch(monkeypatch, _judged(_dims()))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.diagnostics.vocabulary_diversity_pct == SIG.vocabulary_diversity_pct


def test_ielts_snaps_dimension_bands_to_half(monkeypatch):
    # W4：LLM 返回非半档 band，各维须对齐 0.5 再聚合
    _patch(monkeypatch, _judged(_dims((6.1, 6.4, 6.6, 6.9))))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.dimensions.fluency_coherence.band == 6.0
    assert rep.dimensions.lexical_resource.band == 6.5
    assert rep.dimensions.grammatical_range_accuracy.band == 6.5
    assert rep.dimensions.pronunciation.band == 7.0
    assert rep.overall_band == 6.5                        # snapped 均值 6.25 → 6.5


# —— 音频切片（P1：只喂 2–3 段最长，优先 file URI）—— #
def _wav(tmp_path, name="a.wav"):
    p = tmp_path / name
    p.write_bytes(b"RIFFxxxxWAVE")
    return str(p)


def test_select_pronunciation_clips_picks_longest():
    clips = [AudioClip(path=f"/c{i}.wav", duration_s=d) for i, d in enumerate([3.0, 9.0, 1.0, 7.0, 5.0])]
    picked = judge_run.select_pronunciation_clips(clips)
    assert [c.duration_s for c in picked] == [9.0, 7.0, 5.0]


def test_ielts_feeds_at_most_three_longest_clips(monkeypatch, tmp_path):
    fake = _patch(monkeypatch, _judged(_dims()))
    clips = [
        AudioClip(path=_wav(tmp_path, f"c{i}.wav"), duration_s=float(i + 1))
        for i in range(5)
    ]
    judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, clips=clips)
    contents = fake.models.last["contents"]
    assert len(contents) == 1 + 3                        # prompt + 3 段最长切片


def test_clip_part_prefers_file_uri_over_bytes(monkeypatch, tmp_path):
    # 预上传过的切片引用 URI（不读文件）；没有 URI 的回退 inline bytes
    fake = _patch(monkeypatch, _judged(_dims()))
    with_uri = AudioClip(path="/never/read.wav", duration_s=9.0, file_uri="files/abc")
    with_bytes = AudioClip(path=_wav(tmp_path), duration_s=5.0, file_uri=None)
    judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, clips=[with_uri, with_bytes])
    _, part_uri, part_bytes = fake.models.last["contents"]
    assert part_uri.file_data.file_uri == "files/abc"
    assert part_bytes.inline_data.data == b"RIFFxxxxWAVE"


def test_ielts_without_clips_warns_and_skips(monkeypatch, caplog):
    # IELTS 无切片不报错，只 warning，且不喂音频 Part
    fake = _patch(monkeypatch, _judged(_dims()))
    with caplog.at_level("WARNING"):
        judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG, clips=None)
    assert len(fake.models.last["contents"]) == 1
    assert any("未提供音频" in r.message for r in caplog.records)


def test_ielts_missing_clip_file_raises(monkeypatch):
    # 给了路径但文件不存在且无 URI → 明确报错
    _patch(monkeypatch, _judged(_dims()))
    with pytest.raises(FileNotFoundError):
        judge_run.run_judge(
            mode="ielts", transcript=TR, signals=SIG,
            clips=[AudioClip(path="/no/such.wav", duration_s=1.0)],
        )


def test_scenario_forces_no_band_and_no_audio(monkeypatch):
    # 即便 LLM 误填了四维，情景也必须被强制清空，且不喂音频
    fake = _patch(monkeypatch, _judged(_dims()))
    rep = judge_run.run_judge(
        mode="scenario", transcript=TR, signals=SIG,
        scenario_case="ordering",
        clips=[AudioClip(path="/should/not/be/read.wav", duration_s=1.0)],
    )
    assert rep.dimensions is None
    assert rep.overall_band is None
    assert len(fake.models.last["contents"]) == 1        # 情景不喂音频


# —— unscorable 边界 —— #
def test_ielts_missing_dimensions_marks_unscorable(monkeypatch):
    # 雅思 judge 拒评（dimensions=None）不抛错：标记 unscorable，保留诊断层
    _patch(monkeypatch, _judged(None))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.unscorable is True
    assert rep.unscorable_reason == judge_run.UNSCORABLE_REASON
    assert rep.dimensions is None
    assert rep.overall_band is None
    assert rep.diagnostics.vocabulary_diversity_pct == SIG.vocabulary_diversity_pct  # 诊断层保留


def test_ielts_scorable_is_not_unscorable(monkeypatch):
    _patch(monkeypatch, _judged(_dims()))
    rep = judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)
    assert rep.unscorable is False
    assert rep.unscorable_reason is None
    assert rep.overall_band == 6.5


def test_scenario_dimensions_none_is_not_unscorable(monkeypatch):
    # 情景对话 dimensions=None 是设计上的正常态，绝不能被误标 unscorable
    _patch(monkeypatch, _judged(None))
    rep = judge_run.run_judge(mode="scenario", transcript=TR, signals=SIG, scenario_case="ordering")
    assert rep.unscorable is False
    assert rep.unscorable_reason is None
    assert rep.dimensions is None


# —— 解析兜底 —— #
def test_missing_diagnostics_is_infra_failure_not_unscorable(monkeypatch):
    # 响应缺 required 的 diagnostics（schema 违约）→ 按基础设施错误抛（走 failed），
    # 不得标 unscorable——系统故障不该引导用户「重录」。
    d = json.loads(_judged(None).model_dump_json())
    d.pop("diagnostics")
    _patch(monkeypatch, None, text=json.dumps(d))
    with pytest.raises(RuntimeError, match="judge 响应解析失败"):
        judge_run.run_judge(mode="ielts", transcript=TR, signals=SIG)


def test_parsed_none_falls_back_to_json_text(monkeypatch):
    # 结构化 parsed 为空时，用 resp.text 的合法 JSON 兜底
    text = _judged(None).model_dump_json()
    _patch(monkeypatch, None, text=text)
    rep = judge_run.run_judge(mode="scenario", transcript=TR, signals=SIG, scenario_case="ordering")
    assert rep.dimensions is None
    assert rep.diagnostics.vocabulary_diversity_pct == SIG.vocabulary_diversity_pct


def test_parsed_none_and_bad_text_raises_with_context(monkeypatch):
    # parsed 为空且 text 不合法 → 抛带上下文的 RuntimeError
    _patch(monkeypatch, None, text="")
    with pytest.raises(RuntimeError, match="judge 响应解析失败"):
        judge_run.run_judge(mode="scenario", transcript=TR, signals=SIG, scenario_case="ordering")


def test_empty_transcript_does_not_crash(monkeypatch):
    # 空 transcript / 空 words / 零时长 不应崩
    _patch(monkeypatch, _judged(_dims()))
    empty_tr = Transcript(text="", language="en", duration=0.0, words=[])
    empty_sig = compute_signals([], 0.0)
    rep = judge_run.run_judge(mode="ielts", transcript=empty_tr, signals=empty_sig)
    assert rep.practice_summary.speaking_time_s == 0.0
    assert rep.diagnostics.vocabulary_diversity_pct == 0.0   # 空输入 TTR 回填为 0


def test_empty_transcript_judge_refusal_marks_unscorable(monkeypatch):
    # 空输入的真实路径：judge 依 grounding 铁律拒评（dimensions=None）→ unscorable
    _patch(monkeypatch, _judged(None))
    empty_tr = Transcript(text="", language="en", duration=0.0, words=[])
    empty_sig = compute_signals([], 0.0)
    rep = judge_run.run_judge(mode="ielts", transcript=empty_tr, signals=empty_sig, clips=None)
    assert rep.unscorable is True
    assert rep.overall_band is None
    assert rep.dimensions is None


# —— Files API 预上传 —— #
def test_upload_clip_without_api_key_returns_none(monkeypatch):
    # 离线 / 无 key（CI、单测）静默跳过，不碰网络
    monkeypatch.setattr(judge_run.settings, "gemini_api_key", "")
    assert judge_run.upload_clip("/whatever.wav") is None


def test_upload_clip_failure_degrades_to_none(monkeypatch, caplog):
    # 预上传失败只降级（回退 inline bytes），不让会话失败
    monkeypatch.setattr(judge_run.settings, "gemini_api_key", "k")

    class _Files:
        def upload(self, *, file, config):
            raise RuntimeError("network down")

    fake = type("C", (), {"files": _Files()})()
    monkeypatch.setattr(judge_run, "_client", lambda: fake)
    with caplog.at_level("WARNING"):
        assert judge_run.upload_clip("/a.wav") is None
    assert any("预上传失败" in r.message for r in caplog.records)


def test_upload_clip_returns_uri(monkeypatch):
    monkeypatch.setattr(judge_run.settings, "gemini_api_key", "k")

    class _Files:
        def upload(self, *, file, config):
            return type("F", (), {"uri": "files/xyz"})()

    fake = type("C", (), {"files": _Files()})()
    monkeypatch.setattr(judge_run, "_client", lambda: fake)
    assert judge_run.upload_clip("/a.wav") == "files/xyz"
