"""/ws/live WS 代理单测。Gemini Live 会话被 fake 替换，零网络、确定性。

覆盖：连接参数校验（mode/case/turn）、建链 session_started + sessions 落库、
上行音频帧转发（含 mime）、下行音频 binary、转写 transcript_delta 事件、
interrupted / turn_complete 事件转发、end_session 收束并触发课后 finalize、
客户端断开不触发 finalize、未知控制不致断流、Live 连接失败回报 error 事件。
"""

import asyncio
import json
import threading
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
    """

    def __init__(self, responses):
        self.sent: list = []
        self._responses = responses
        self._first = True

    async def send_realtime_input(self, *, audio):
        self.sent.append(audio)

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
    """默认掐掉课后 finalize（真实现要跑 whisper/judge）；专项测试自行覆盖。"""
    monkeypatch.setattr("app.api.live_ws.finalize_session", lambda session_id: None)
    yield
    # 模块级任务集是跨测试的进程态，清掉防慢任务句柄漏到下个用例（review S3）
    live_ws_module._finalize_tasks.clear()


def _patch_session(monkeypatch, session) -> None:
    @asynccontextmanager
    async def fake_connect():
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
    _patch_session(monkeypatch, FakeLiveSession(responses=[]))

    with client.websocket_connect("/ws/live?mode=ielts_a&turn=natural") as ws:
        event = ws.receive_json()        # 建链第一条消息即 session_started
        assert event["type"] == "session_started"
        session_id = event["session_id"]
        ws.send_text(json.dumps({"type": "end_session"}))

    row = crud.get_session(session_id)
    assert row["mode"] == "ielts"
    assert row["sub_mode"] == "exam"     # ielts_a ↦ mode=ielts + sub_mode=exam
    assert row["scenario_case"] is None


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

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert _session_count() == 0


def test_live_connect_failure_leaves_no_session_row(client, monkeypatch):
    @asynccontextmanager
    async def broken_connect():
        raise RuntimeError("live 连不上")
        yield  # pragma: no cover

    monkeypatch.setattr("app.api.live_ws.connect_live", broken_connect)

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
        event = ws.receive_json()
    assert event["type"] == "error"
    assert "实时会话异常" in event["message"]
    assert _session_count() == 0         # Live 建链失败不留孤儿行


# ---------- 双向桥接 ----------


def test_upstream_audio_forwarded_with_mime(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
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

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
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

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
        ws.receive_json()                # session_started
        assert ws.receive_bytes() == b"\x0c"
        assert ws.receive_json() == {"type": "interrupted"}
        assert ws.receive_json() == {"type": "turn_complete"}
        ws.send_text(json.dumps({"type": "end_session"}))


def test_unknown_control_does_not_kill_session(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
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

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
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

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
        ws.receive_json()                # session_started
        assert ws.receive_bytes() == b"\x0a"
        ev = ws.receive_json()
        assert (ev["role"], ev["text"]) == ("examiner", "Hi")
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

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
        session_id = ws.receive_json()["session_id"]
        ws.send_text(json.dumps({"type": "end_session"}))

    # finalize 在 WS 关闭后丢线程后台跑，等它落地
    assert called.wait(timeout=5), "end_session 后 finalize 未被触发"
    assert finalized == [session_id]


def test_client_disconnect_does_not_trigger_finalize(client, monkeypatch):
    session = FakeLiveSession(responses=[])
    _patch_session(monkeypatch, session)
    called = threading.Event()
    monkeypatch.setattr(
        "app.api.live_ws.finalize_session", lambda session_id: called.set()
    )

    with client.websocket_connect("/ws/live?mode=ielts_a") as ws:
        session_id = ws.receive_json()["session_id"]
        ws.send_bytes(b"\x09")
    # with 块退出即客户端断开（未发 end_session）；服务端正常收束、无悬挂

    assert len(session.sent) == 1
    assert not called.wait(timeout=0.3)  # 中途断开不触发 judge（仅 end_session 触发）
    assert crud.get_session(session_id)["status"] == "recording"  # 弃局停在 recording
