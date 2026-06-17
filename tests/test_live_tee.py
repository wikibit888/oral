"""UserAudioTee 单测：地板状态机 + 切片边界/时间戳 + 预缓冲回补，零网络零 whisper。

帧用 0.5s（16000 字节 @ 32000 B/s）为基本单位，时间戳全部可手算；
save_clip / ingest_clip 打桩记录调用，drain 后断言。
"""

import asyncio

import pytest

from app.live import tee as tee_module
from app.live.tee import BYTES_PER_SECOND, UserAudioTee

HALF_SEC = b"\x01" * (BYTES_PER_SECOND // 2)   # 0.5s 帧


@pytest.fixture
def ingested(monkeypatch):
    """打桩切片落盘 + 转写段 + 收口段，返回记录列表 [(seq, n_bytes, start_ts, end_ts)]。

    PR-1b 后 tee 不再调 ingest_clip，而是分两段：transcribe_clip（持锁串行，记录于此）
    + finalize_clip（脱锁并发，无副作用打桩）。记录在转写段——它在锁内按 seq 顺序执行，
    故 calls 顺序即切片 seq 序。
    """
    calls: list[tuple] = []
    pcm_by_path: dict[str, bytes] = {}

    def fake_save(session_id, seq, pcm):
        path = f"/fake/{session_id}_turn{seq:03d}.wav"
        pcm_by_path[path] = pcm
        return path

    def fake_transcribe_clip(session_id, path, *, role="user", start_ts=None, end_ts=None):
        seq = int(path.rsplit("turn", 1)[1].split(".")[0])
        calls.append((seq, len(pcm_by_path[path]), start_ts, end_ts))
        return seq, None                  # (turn_id, transcript)——收口段不校验内容

    def fake_finalize_clip(turn_id, clip_path, transcript):
        pass

    monkeypatch.setattr(tee_module, "save_clip", fake_save)
    monkeypatch.setattr(tee_module, "transcribe_clip", fake_transcribe_clip)
    monkeypatch.setattr(tee_module, "finalize_clip", fake_finalize_clip)
    return calls


def test_clip_cut_when_model_speaks(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_user_frame(HALF_SEC)          # 1.0s 用户音频
        t.on_model_audio()                 # 考官开口 → 封切片
        t.on_model_audio()                 # 后续考官帧不再切
        await t.drain()

    asyncio.run(scenario())
    assert ingested == [(0, BYTES_PER_SECOND, 0.0, 1.0)]


def test_turn_complete_opens_next_clip(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_user_frame(HALF_SEC)          # [0, 1.0) 第一轮
        t.on_model_audio()
        t.on_user_frame(HALF_SEC)          # 考官说话期间的麦克风帧（不进切片）
        t.on_turn_complete()               # 地板归还，丢弃预缓冲
        t.on_user_frame(HALF_SEC)          # [1.5, 2.0) 第二轮
        t.finish()
        await t.drain()

    asyncio.run(scenario())
    assert ingested == [
        (0, BYTES_PER_SECOND, 0.0, 1.0),
        (1, BYTES_PER_SECOND // 2, 1.5, 2.0),
    ]


def test_interrupted_restores_prebuffer(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()                 # 切片1 [0, 1.0)
        t.on_user_frame(HALF_SEC)          # 打断的起头：先进预缓冲（事件还没到）
        t.on_interrupted()                 # barge-in → 预缓冲回补切片头
        t.on_user_frame(HALF_SEC)          # 打断后继续说
        t.finish()
        await t.drain()

    asyncio.run(scenario())
    # 切片2 起点回拨到打断起头（1.0），含预缓冲 0.5s + 后续 0.5s
    assert ingested == [
        (0, BYTES_PER_SECOND, 0.0, 1.0),
        (1, BYTES_PER_SECOND, 1.0, 2.0),
    ]


def test_prebuffer_capped_at_two_seconds(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()                 # 切片1 [0, 1.0)
        for _ in range(6):                 # 考官说话期间 3.0s 帧，预缓冲只留最近 2.0s
            t.on_user_frame(HALF_SEC)
        t.on_interrupted()
        t.finish()
        await t.drain()

    asyncio.run(scenario())
    # pos=4.0，回补 2.0s → 切片2 [2.0, 4.0)
    assert ingested == [
        (0, BYTES_PER_SECOND, 0.0, 1.0),
        (1, 2 * BYTES_PER_SECOND, 2.0, 4.0),
    ]


def test_turn_complete_after_interrupted_is_noop(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()                 # 切片1
        t.on_user_frame(HALF_SEC)          # 预缓冲
        t.on_interrupted()                 # 先到：回补，起点 1.0
        t.on_turn_complete()               # 后到：不得重置已开始累积的切片
        t.on_user_frame(HALF_SEC)
        t.finish()
        await t.drain()

    asyncio.run(scenario())
    assert ingested[1] == (1, BYTES_PER_SECOND, 1.0, 2.0)


def test_short_or_empty_clip_dropped(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_model_audio()                 # 考官先开口（雅思开场）：空切片丢弃
        t.on_turn_complete()
        t.on_user_frame(b"\x01" * 6400)    # 0.2s < 最短 0.4s → 丢弃
        t.on_model_audio()
        t.on_turn_complete()
        t.on_user_frame(HALF_SEC)          # 0.5s 正常切片
        t.finish()
        await t.drain()

    asyncio.run(scenario())
    assert len(ingested) == 1
    seq, n, start, end = ingested[0]
    assert n == BYTES_PER_SECOND // 2
    assert (start, end) == (0.2, 0.7)      # 流位置时钟包含被丢弃帧的时长


def test_finish_without_floor_cuts_nothing(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()                 # 切片1 [0, 0.5)
        t.on_user_frame(HALF_SEC)          # 考官说话期间（预缓冲）
        t.finish()                         # 地板不在用户手上：不切预缓冲
        await t.drain()

    asyncio.run(scenario())
    assert ingested == [(0, BYTES_PER_SECOND // 2, 0.0, 0.5)]


def test_zero_frame_session(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.finish()                         # 用户全程没说话：无切片、不抛
        await t.drain()

    asyncio.run(scenario())
    assert ingested == []


def test_finish_idempotent_and_gates_hooks(ingested):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.finish()                         # 封尾切片
        t.finish()                         # 二次 finish 不得重复切
        # end_session 后 Live 缓冲的事件仍可能再走一拍钩子（review W1）：
        # 不得翻转地板、不得再切出 drain 快照外的新切片
        t.on_turn_complete()
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()
        await t.drain()

    asyncio.run(scenario())
    assert ingested == [(0, BYTES_PER_SECOND // 2, 0.0, 0.5)]


def test_transcribe_failure_swallowed(ingested, monkeypatch, caplog):
    # 转写段（持锁）失败：吞掉并记日志，不拖垮会话，且不进入上传段
    def boom(*args, **kwargs):
        raise RuntimeError("whisper 炸了")

    monkeypatch.setattr(tee_module, "transcribe_clip", boom)

    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()
        await t.drain()                    # 不抛——单切片失败不拖垮会话

    asyncio.run(scenario())
    assert "tee 切片转写失败" in caplog.text


def test_finalize_failure_swallowed(ingested, monkeypatch, caplog):
    # 上传/收口段（脱锁）失败：同样吞掉并记日志，不拖垮会话/其余切片
    def boom(*args, **kwargs):
        raise RuntimeError("上传炸了")

    monkeypatch.setattr(tee_module, "finalize_clip", boom)

    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()
        await t.drain()

    asyncio.run(scenario())
    assert "tee 切片上传/收口失败" in caplog.text


# ---------- 考官/AI 音频按轮捕获（dialog 回看，纯回放、不进评测）----------

EX_HALF_SEC = b"\x02" * (48000 // 2)       # 0.5s 考官帧（24k×16bit×mono = 48000 B/s）


@pytest.fixture
def examiner(monkeypatch):
    """打桩考官切片落盘 + assistant turn 落库，返回记录 [(role, clip, start, end, text)]。"""
    calls: list[tuple] = []

    def fake_save_ex(session_id, seq, pcm):
        return f"/fake/{session_id}_examiner{seq:03d}.wav"

    def fake_create_turn(*, session_id, role, clip_path, start_ts=None, end_ts=None, text=None):
        calls.append((role, clip_path, start_ts, end_ts, text))
        return len(calls)

    monkeypatch.setattr(tee_module, "save_examiner_clip", fake_save_ex)
    monkeypatch.setattr(tee_module.crud, "create_turn", fake_create_turn)
    return calls


async def _drain_examiner(t):
    await t.drain()
    await asyncio.gather(*t._examiner_tasks, return_exceptions=True)


def test_examiner_clip_captured_on_turn_complete(ingested, examiner):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_user_frame(HALF_SEC)              # user [0, 1.0)
        t.on_model_audio(EX_HALF_SEC)          # 考官开口：封 user 切片 + 累积考官音频
        t.on_examiner_transcript("Hello, ")
        t.on_model_audio(EX_HALF_SEC)          # 1.0s 考官音频
        t.on_examiner_transcript("welcome.")
        t.on_turn_complete()                   # 考官轮结束 → 封考官切片
        t.on_user_frame(HALF_SEC)              # 下一轮用户
        t.finish()
        await _drain_examiner(t)

    asyncio.run(scenario())
    # 用户切片仍正常（考官捕获不污染评测链路）。本场未模拟考官说话期间的麦克风帧，
    # 故 _pos 在考官段不前进：第二轮用户切片从 1.0 起 [1.0, 1.5)。
    assert ingested == [(0, BYTES_PER_SECOND, 0.0, 1.0), (1, BYTES_PER_SECOND // 2, 1.0, 1.5)]
    # 考官一条 assistant 回合：文本拼接、有切片、start_ts = 考官开口时的 _pos(=1.0)
    assert len(examiner) == 1
    role, clip, start, end, text = examiner[0]
    assert role == "assistant"
    assert clip is not None and "examiner000" in clip
    assert text == "Hello, welcome."
    assert start == 1.0


def test_examiner_clip_cut_on_barge_in(ingested, examiner):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio(EX_HALF_SEC)          # 考官说
        t.on_examiner_transcript("Let me explain")
        t.on_interrupted()                     # 用户打断 → 封考官残段
        t.finish()
        await _drain_examiner(t)

    asyncio.run(scenario())
    assert len(examiner) == 1
    assert examiner[0][0] == "assistant"
    assert examiner[0][4] == "Let me explain"


def test_examiner_clip_flushed_on_finish_if_examiner_talking(ingested, examiner):
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio(EX_HALF_SEC)          # 考官还在说时用户直接 End
        t.on_examiner_transcript("Goodbye.")
        t.finish()                             # 末轮考官 → finish 封最后一个考官切片
        await _drain_examiner(t)

    asyncio.run(scenario())
    assert len(examiner) == 1
    assert examiner[0][4] == "Goodbye."


def test_no_examiner_clip_when_data_is_none(ingested, examiner):
    """旧调用方/无 data 的 on_model_audio 只作边界信号，不产出考官回合（向后兼容）。"""
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()                     # 无 data
        t.on_turn_complete()
        t.finish()
        await _drain_examiner(t)

    asyncio.run(scenario())
    assert examiner == []


def test_examiner_text_only_turn_saved_without_clip(ingested, examiner):
    """只有转写、没有音频字节（on_model_audio 无 data）的考官轮：仍落 assistant 行
    （text 在、clip_path=None），dialog 才不丢这一句。"""
    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()                     # 边界信号，无音频字节
        t.on_examiner_transcript("Thank you. That is the end.")
        t.on_turn_complete()
        t.finish()
        await _drain_examiner(t)

    asyncio.run(scenario())
    assert len(examiner) == 1
    role, clip, _start, _end, text = examiner[0]
    assert role == "assistant"
    assert clip is None                        # 无音频 → 无切片路径
    assert text == "Thank you. That is the end."
