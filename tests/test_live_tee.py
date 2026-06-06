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
    """打桩切片落盘 + ingest，返回记录列表 [(seq, n_bytes, start_ts, end_ts)]。"""
    calls: list[tuple] = []
    pcm_by_path: dict[str, bytes] = {}

    def fake_save(session_id, seq, pcm):
        path = f"/fake/{session_id}_turn{seq:03d}.wav"
        pcm_by_path[path] = pcm
        return path

    def fake_ingest(session_id, path, *, role="user", start_ts=None, end_ts=None):
        seq = int(path.rsplit("turn", 1)[1].split(".")[0])
        calls.append((seq, len(pcm_by_path[path]), start_ts, end_ts))

    monkeypatch.setattr(tee_module, "save_clip", fake_save)
    monkeypatch.setattr(tee_module, "ingest_clip", fake_ingest)
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


def test_ingest_failure_swallowed(ingested, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("whisper 炸了")

    monkeypatch.setattr(tee_module, "ingest_clip", boom)

    async def scenario():
        t = UserAudioTee("s1")
        t.on_user_frame(HALF_SEC)
        t.on_model_audio()
        await t.drain()                    # 不抛——单切片失败不拖垮会话

    asyncio.run(scenario())
    assert "tee 切片 ingest 失败" in caplog.text
