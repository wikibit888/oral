"""/ws/live WS 代理单测。Gemini Live 会话被 fake 替换，零网络、确定性。

覆盖：连接参数校验（mode/case/turn）、建链 session_started + sessions 落库、
上行音频帧转发（含 mime）、下行音频 binary、转写 transcript_delta 事件、
interrupted / turn_complete 事件转发、end_session 收束并触发课后 finalize、
客户端断开不触发 finalize、未知控制不致断流、Live 连接失败回报 error 事件。
"""

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import crud
from app.api import live_ws as live_ws_module
from app.config import settings
from app.db import get_connection
from app.live.client import AUDIO_MIME
from app.main import app


def _sc(**overrides):
    """server_content 假体：真 SDK 的 LiveServerContent 各字段恒存在（默认 None）。"""
    fields = {
        "input_transcription": None,
        "output_transcription": None,
        "interrupted": None,
        "turn_complete": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _audio_resp(data: bytes):
    return SimpleNamespace(data=data, server_content=None)


def _transcript_resp(user: str | None = None, examiner: str | None = None):
    sc = _sc(
        input_transcription=SimpleNamespace(text=user) if user else None,
        output_transcription=SimpleNamespace(text=examiner) if examiner else None,
    )
    return SimpleNamespace(data=None, server_content=sc)


class FakeLiveSession:
    """最小 Live 会话假体：记录上行；下行先吐完 canned responses，再永久挂起。

    永久挂起模拟真 Live 长连接（迭代器轮间续接由 bridge 的 while True 处理），
    桥的收束依赖上行端（end_session / 断开）触发取消。
    sent 记录全部上行（音频 Blob / ActivityStart / ActivityEnd，按发送顺序）。
    """

    def __init__(self, responses):
        self.sent: list = []
        self.directions: list = []
        self._responses = responses
        self._first = True

    async def send_client_content(self, *, turns, turn_complete=True):
        self.directions.append(turns)      # 导演提示（方式 A）

    async def send_realtime_input(self, *, audio=None, activity_start=None, activity_end=None):
        self.sent.append(audio if audio is not None else (activity_start or activity_end))

    @property
    def sent_audio(self) -> list:
        return [s for s in self.sent if hasattr(s, "data")]

    def receive(self):
        async def gen():
            if self._first:
                self._first = False
                for r in self._responses:
                    yield r
            else:
                await asyncio.Event().wait()   # 挂起直到被取消

        return gen()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def no_finalize(monkeypatch):
    """默认掐掉课后 finalize 与切片 ingest（真实现要跑 whisper/judge）；专项测试自行覆盖。"""
    monkeypatch.setattr("app.api.live_ws.finalize_session", lambda session_id: None)
    monkeypatch.setattr("app.live.tee.save_clip", lambda sid, seq, pcm: f"/fake/{sid}_{seq}.wav")
    monkeypatch.setattr("app.live.tee.ingest_clip", lambda *a, **kw: None)
    yield
    # 模块级任务集是跨测试的进程态，清掉防慢任务句柄漏到下个用例（review S3）
    live_ws_module._background_tasks.clear()


def _patch_session(monkeypatch, session) -> None:
    @asynccontextmanager
    async def fake_connect(turn_mode="natural", system_instruction=None):
        session.turn_mode = turn_mode  # 记录穿透到连接层的轮次模式
        session.system_instruction = system_instruction  # persona（方式 A 考官）
        yield session

    monkeypatch.setattr("app.api.live_ws.connect_live", fake_connect)


def _session_count() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


# ---------- 连接参数校验 ----------


@pytest.mark.parametrize(
    "query",
    [
        "",                              # 缺 mode
        "?mode=bogus",                   # 未知 mode
        "?mode=ielts",                   # WS 侧只认 ielts_a（方式 B 不走 Live）
        "?mode=scenario",                # scenario 缺 case
        "?mode=scenario&case=bogus",     # 未知 case
        "?mode=ielts_a&turn=bogus",      # 未知 turn
    ],
)
def test_invalid_params_rejected_before_live(client, query):
    # 不打 connect_live 补丁：校验必须发生在连 Live 之前，否则这里会真联网/炸
    with client.websocket_connect(f"/ws/live{query}") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert _session_count() == 0         # 参数错不留孤儿会话行


# ---------- 建链：session_started + sessions 落库 ----------


def test_session_started_creates_ielts_a_row(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=ielts_a&turn=natural") as ws:
        event = ws.receive_json()        # 建链第一条消息即 session_started
        assert event["type"] == "session_started"
        session_id = event["session_id"]
        # 方式 A：导演随即开场（P1）
        assert ws.receive_json() == {"type": "part_change", "part": "p1"}
        ws.send_text(json.dumps({"type": "end_session"}))

    row = crud.get_session(session_id)
    assert row["mode"] == "ielts"
    assert row["sub_mode"] == "exam"     # ielts_a ↦ mode=ielts + sub_mode=exam
    assert row["scenario_case"] is None
    # 方式 A 注入中立考官 persona + 导演开场提示已发给 Live
    assert session.system_instruction is not None and "examiner" in session.system_instruction
    assert len(session.directions) == 1


@pytest.mark.parametrize("case", ["ordering", "meeting"])
def test_session_started_creates_scenario_row(client, monkeypatch, case):
    _patch_session(monkeypatch, FakeLiveSession(responses=[]))

    with client.websocket_connect(f"/ws/live?mode=scenario&case={case}&turn=ptt") as ws:
        event = ws.receive_json()
        assert event["type"] == "session_started"
        session_id = event["session_id"]
        ws.send_text(json.dumps({"type": "end_session"}))

    row = crud.get_session(session_id)
    assert row["mode"] == "scenario"
    assert row["sub_mode"] is None
    assert row["scenario_case"] == case


def test_create_session_failure_reports_error(client, monkeypatch):
    # Live 建链成功但落库炸（如 DB 锁死）：应回 error 事件、不悬挂、不留半截会话
    _patch_session(monkeypatch, FakeLiveSession(responses=[]))

    def boom(**kwargs):
        raise RuntimeError("db 炸了")

    monkeypatch.setattr("app.api.live_ws.crud.create_session", boom)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert _session_count() == 0


def test_live_connect_failure_leaves_no_session_row(client, monkeypatch):
    @asynccontextmanager
    async def broken_connect():
        raise RuntimeError("live 连不上")
        yield  # pragma: no cover

    monkeypatch.setattr("app.api.live_ws.connect_live", broken_connect)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert "实时会话异常" in event["message"]
    assert _session_count() == 0         # Live 建链失败不留孤儿行


# ---------- 双向桥接 ----------


def test_upstream_audio_forwarded_with_mime(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                # session_started
        ws.send_bytes(b"\x01\x02\x03\x04")
        ws.send_text(json.dumps({"type": "end_session"}))

    assert len(session.sent) == 1
    blob = session.sent[0]
    assert blob.data == b"\x01\x02\x03\x04"
    assert blob.mime_type == AUDIO_MIME      # audio/pcm;rate=16000


def test_downstream_audio_and_transcripts(client, monkeypatch):
    session = FakeLiveSession(
        responses=[
            _audio_resp(b"\xaa\xbb"),
            _transcript_resp(user="hello"),
            _transcript_resp(examiner="Hi, tell me about your hometown."),
        ]
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                # session_started
        assert ws.receive_bytes() == b"\xaa\xbb"          # 24k PCM 直转 binary
        assert ws.receive_json() == {
            "type": "transcript_delta", "role": "user", "text": "hello",
        }
        assert ws.receive_json() == {
            "type": "transcript_delta",
            "role": "examiner",
            "text": "Hi, tell me about your hometown.",
        }
        ws.send_text(json.dumps({"type": "end_session"}))


def test_interrupted_and_turn_complete_forwarded(client, monkeypatch):
    # barge-in 响应里常带被截断回合的残留音频：先转音频再发 interrupted，
    # 前端按事件清空播放队列时残留字节一并清掉
    session = FakeLiveSession(
        responses=[
            SimpleNamespace(data=b"\x0c", server_content=_sc(interrupted=True)),
            SimpleNamespace(data=None, server_content=_sc(turn_complete=True)),
        ]
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                # session_started
        assert ws.receive_bytes() == b"\x0c"
        assert ws.receive_json() == {"type": "interrupted"}
        assert ws.receive_json() == {"type": "turn_complete"}
        ws.send_text(json.dumps({"type": "end_session"}))


def test_unknown_control_does_not_kill_session(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                # session_started
        ws.send_text(json.dumps({"type": "no_such_control"}))
        ws.send_text("not even json")
        ws.send_bytes(b"\x05\x06")                         # 之后音频仍能过桥
        ws.send_text(json.dumps({"type": "end_session"}))

    assert len(session.sent) == 1
    assert session.sent[0].data == b"\x05\x06"


def test_downstream_failure_reports_error_event(client, monkeypatch):
    # Live 流中途断：已发的音频送达后，客户端应收到 error 事件、连接收束
    class BrokenSession(FakeLiveSession):
        def receive(self):
            async def gen():
                yield _audio_resp(b"\x01")
                raise RuntimeError("live 流断了")

            return gen()

    _patch_session(monkeypatch, BrokenSession(responses=[]))

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                # session_started
        assert ws.receive_bytes() == b"\x01"
        event = ws.receive_json()
    assert event["type"] == "error"


def test_same_response_audio_and_transcript(client, monkeypatch):
    # 同一个 response 里既有音频又有转写：两者都要发出、顺序为先音频后事件
    resp = SimpleNamespace(
        data=b"\x0a",
        server_content=_sc(output_transcription=SimpleNamespace(text="Hi")),
    )
    _patch_session(monkeypatch, FakeLiveSession(responses=[resp]))

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                # session_started
        assert ws.receive_bytes() == b"\x0a"
        ev = ws.receive_json()
        assert (ev["role"], ev["text"]) == ("examiner", "Hi")
        ws.send_text(json.dumps({"type": "end_session"}))


# ---------- PTT 轮次语义 ----------


def test_ptt_activity_signals(client, monkeypatch):
    # 按下说话首帧前自动补 activity_start；松开发 turn_end → activity_end；
    # 再按下开新一轮再补 start（内建 VAD 已关，这对信号就是轮次边界）
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering&turn=ptt") as ws:
        ws.receive_json()                  # session_started
        ws.send_bytes(b"\x01\x02")         # 第一轮首帧
        ws.send_bytes(b"\x03\x04")         # 同轮第二帧：不重复补 start
        ws.send_text(json.dumps({"type": "turn_end"}))
        ws.send_bytes(b"\x05\x06")         # 第二轮按下
        ws.send_text(json.dumps({"type": "end_session"}))

    assert session.turn_mode == "ptt"      # turn 模式穿透到 Live 连接层
    kinds = [type(s).__name__ for s in session.sent]
    assert kinds == ["ActivityStart", "Blob", "Blob", "ActivityEnd", "ActivityStart", "Blob"]
    assert [b.data for b in session.sent_audio] == [b"\x01\x02", b"\x03\x04", b"\x05\x06"]


def test_natural_no_activity_signals_turn_end_ignored(client, monkeypatch):
    # natural：VAD 自动断轮，不发 activity 信号；turn_end 记日志忽略、不断流
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x01")
        ws.send_text(json.dumps({"type": "turn_end"}))
        ws.send_bytes(b"\x02")
        ws.send_text(json.dumps({"type": "end_session"}))

    assert session.turn_mode == "natural"
    assert [type(s).__name__ for s in session.sent] == ["Blob", "Blob"]


def test_ptt_turn_end_before_any_audio_ignored(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering&turn=ptt") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"type": "turn_end"}))   # 还没按下：activity 未开
        ws.send_text(json.dumps({"type": "end_session"}))

    assert session.sent == []              # 不发无配对的 activity_end


# ---------- 延迟徽章 latency_ms ----------


def test_latency_ms_emitted_once_on_examiner_first_frame(client, monkeypatch):
    # natural：用户非静音帧采停说点 → 考官首帧后发 latency_ms（一轮一次）
    loud = b"\x00\x08" * 1600     # 0.1s，采样值 2048 > 静音阈值
    session = TriggeredFakeLiveSession(
        responses=[_audio_resp(b"\x0a"), _audio_resp(b"\x0b")],
        trigger_bytes=len(loud),
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                      # session_started
        ws.send_bytes(loud)
        assert ws.receive_bytes() == b"\x0a"   # 考官首帧
        ev = ws.receive_json()
        assert ev["type"] == "latency_ms"
        assert isinstance(ev["value"], int) and ev["value"] >= 0
        assert ws.receive_bytes() == b"\x0b"   # 第二帧后没有再发（中间无 text 帧）
        ws.send_text(json.dumps({"type": "end_session"}))


def test_latency_ms_ptt_after_turn_end(client, monkeypatch):
    # ptt：静音帧也可（不看幅值），turn_end 才是停说时刻
    quiet = b"\x01" * 16000
    session = TriggeredFakeLiveSession(
        responses=[_audio_resp(b"\x0a")],
        trigger_on_activity_end=True,
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering&turn=ptt") as ws:
        ws.receive_json()
        ws.send_bytes(quiet)
        ws.send_text(json.dumps({"type": "turn_end"}))
        assert ws.receive_bytes() == b"\x0a"
        ev = ws.receive_json()
        assert ev["type"] == "latency_ms" and ev["value"] >= 0
        ws.send_text(json.dumps({"type": "end_session"}))


@pytest.mark.parametrize("turn", ["natural", "ptt"])
def test_no_latency_ms_when_user_never_spoke(client, monkeypatch, turn):
    # 考官先开口（雅思开场）：无停说点，不发 latency_ms——两种轮次模式同语义
    session = FakeLiveSession(
        responses=[_audio_resp(b"\x0a"), _transcript_resp(examiner="Hello!")]
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect(f"/ws/live?mode=scenario&case=ordering&turn={turn}") as ws:
        ws.receive_json()
        assert ws.receive_bytes() == b"\x0a"
        ev = ws.receive_json()                 # 下一条 text 直接是转写，无 latency_ms
        assert ev["type"] == "transcript_delta"
        ws.send_text(json.dumps({"type": "end_session"}))


# ---------- 收束 → 课后 finalize ----------


def test_end_session_triggers_finalize(client, monkeypatch):
    _patch_session(monkeypatch, FakeLiveSession(responses=[]))
    called = threading.Event()
    finalized: list[str] = []

    def fake_finalize(session_id):
        finalized.append(session_id)
        called.set()

    monkeypatch.setattr("app.api.live_ws.finalize_session", fake_finalize)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        session_id = ws.receive_json()["session_id"]
        ws.send_text(json.dumps({"type": "end_session"}))

    # finalize 在 WS 关闭后丢线程后台跑，等它落地
    assert called.wait(timeout=5), "end_session 后 finalize 未被触发"
    assert finalized == [session_id]


class TriggeredFakeLiveSession(FakeLiveSession):
    """收满 trigger_bytes 上行音频字节（或 PTT 的 activity_end）才放下行
    canned responses——保证「用户先说、考官才开口」的时序确定，消除两泵竞态。"""

    def __init__(self, responses, trigger_bytes=0, trigger_on_activity_end=False):
        super().__init__(responses)
        self._trigger_bytes = trigger_bytes
        self._trigger_on_activity_end = trigger_on_activity_end
        self._got = 0
        self._event = asyncio.Event()

    async def send_client_content(self, *, turns, turn_complete=True):
        self.directions.append(turns)      # 导演提示（方式 A）

    async def send_realtime_input(self, *, audio=None, activity_start=None, activity_end=None):
        await super().send_realtime_input(
            audio=audio, activity_start=activity_start, activity_end=activity_end
        )
        if self._trigger_on_activity_end:
            if activity_end is not None:
                self._event.set()
        elif audio is not None:
            self._got += len(audio.data)
            if self._got >= self._trigger_bytes:
                self._event.set()

    def receive(self):
        async def gen():
            if self._first:
                self._first = False
                await self._event.wait()
                for r in self._responses:
                    yield r
            else:
                await asyncio.Event().wait()

        return gen()


def test_live_clips_ingested_then_finalized(client, monkeypatch):
    # 全链路缩影：用户 0.5s → 考官音频（封切片1）→ turn_complete → 用户 0.5s
    # → end_session（封切片2）→ 先排干两次 ingest，再 finalize
    order: list[str] = []
    clips: list[tuple] = []
    finalize_done = threading.Event()
    pcm_by_path: dict[str, bytes] = {}

    def fake_save(session_id, seq, pcm):
        path = f"/fake/{session_id}_turn{seq}.wav"
        pcm_by_path[path] = pcm
        return path

    def fake_ingest(session_id, path, *, role="user", start_ts=None, end_ts=None):
        order.append("ingest")
        clips.append((len(pcm_by_path[path]), start_ts, end_ts))

    def fake_finalize(session_id):
        order.append("finalize")
        finalize_done.set()

    monkeypatch.setattr("app.live.tee.save_clip", fake_save)
    monkeypatch.setattr("app.live.tee.ingest_clip", fake_ingest)
    monkeypatch.setattr("app.api.live_ws.finalize_session", fake_finalize)

    half_sec = b"\x01" * 16000  # 0.5s @ 16k/16-bit/mono
    session = TriggeredFakeLiveSession(
        responses=[
            _audio_resp(b"\x0a"),
            SimpleNamespace(data=None, server_content=_sc(turn_complete=True)),
        ],
        trigger_bytes=len(half_sec),
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        ws.receive_json()                          # session_started
        ws.send_bytes(half_sec)                    # 第一轮用户音频
        assert ws.receive_bytes() == b"\x0a"       # 考官开口 → 切片1 已封
        assert ws.receive_json() == {"type": "turn_complete"}
        ws.send_bytes(half_sec)                    # 第二轮用户音频
        ws.send_text(json.dumps({"type": "end_session"}))

    assert finalize_done.wait(timeout=5), "end_session 后未跑到 finalize"
    assert order == ["ingest", "ingest", "finalize"]   # 先排干切片再收口
    assert clips == [(16000, 0.0, 0.5), (16000, 0.5, 1.0)]


def test_client_disconnect_does_not_trigger_finalize(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)
    called = threading.Event()
    monkeypatch.setattr(
        "app.api.live_ws.finalize_session", lambda session_id: called.set()
    )

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        session_id = ws.receive_json()["session_id"]
        ws.send_bytes(b"\x09")
    # with 块退出即客户端断开（未发 end_session）；服务端正常收束、无悬挂

    assert len(session.sent) == 1
    assert not called.wait(timeout=0.3)  # 中途断开不触发 judge（仅 end_session 触发）
    # 零切片弃局（StrictMode 双连接等）→ 孤儿行被后台清理（联调发现③）
    deadline = time.monotonic() + 3
    while crud.get_session(session_id) is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert crud.get_session(session_id) is None, "孤儿行应在 3s 内被后台清理删除"


def test_disconnect_with_clips_keeps_session_row(client, monkeypatch):
    # 说过话（已切出切片）的弃局会话保留素材，停在 live 不触发 judge
    half_sec = b"\x01" * 16000
    session = TriggeredFakeLiveSession(
        responses=[_audio_resp(b"\x0a")],     # 考官开口 → 封切片1
        trigger_bytes=len(half_sec),
    )
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        session_id = ws.receive_json()["session_id"]
        ws.send_bytes(half_sec)
        assert ws.receive_bytes() == b"\x0a"  # 切片已切出（clip_count=1）
    # 断开（未发 end_session）

    time.sleep(0.3)                           # 给孤儿清理任务一个误删的机会窗口
    row = crud.get_session(session_id)
    assert row is not None and row["status"] == "live"


def test_end_session_flips_status_to_processing_immediately(client, monkeypatch):
    # 联调发现①：End 后前端立刻轮询 /reports，drain/ingest 在途窗口里
    # 状态必须已是 processing（finalize 被打桩成 no-op，不会再推进状态）
    _patch_session(monkeypatch, FakeLiveSession(responses=[]))

    with client.websocket_connect("/ws/live?mode=scenario&case=ordering") as ws:
        session_id = ws.receive_json()["session_id"]
        ws.send_text(json.dumps({"type": "end_session"}))

    deadline = time.monotonic() + 3
    while (
        crud.get_session(session_id)["status"] != "processing"
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert crud.get_session(session_id)["status"] == "processing"
