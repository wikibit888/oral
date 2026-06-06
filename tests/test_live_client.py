"""connect_live 建链重试单测（_connect_once 打桩，零网络）。

联调实测 Gemini 建链偶发 TLS 被重置（OSError），重连即通——connect_live
只对**建链**失败重试一次；会话中途异常必须原样上抛、绝不偷偷换新会话。
"""

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.live import client as client_module
from app.live.client import connect_live


def _connect_factory(fail_times: int, exc: Exception, attempts: list):
    """返回 _connect_once 替身：前 fail_times 次 __aenter__ 抛 exc，之后成功。"""

    @asynccontextmanager
    async def fake_connect_once():
        attempts.append(1)
        if len(attempts) <= fail_times:
            raise exc
        yield f"session-{len(attempts)}"

    return fake_connect_once


def test_transient_oserror_retried_once(monkeypatch, caplog):
    attempts: list = []
    monkeypatch.setattr(
        client_module, "_connect_once",
        _connect_factory(1, ConnectionResetError("tls reset"), attempts),
    )

    async def scenario():
        async with connect_live() as session:
            return session

    assert asyncio.run(scenario()) == "session-2"
    assert len(attempts) == 2
    assert "重试一次" in caplog.text


def test_second_failure_raises(monkeypatch):
    attempts: list = []
    monkeypatch.setattr(
        client_module, "_connect_once",
        _connect_factory(2, ConnectionResetError("tls reset"), attempts),
    )

    async def scenario():
        async with connect_live():
            pass

    with pytest.raises(ConnectionResetError):
        asyncio.run(scenario())
    assert len(attempts) == 2              # 只重试一次，不无限重连


def test_non_network_error_not_retried(monkeypatch):
    attempts: list = []
    monkeypatch.setattr(
        client_module, "_connect_once",
        _connect_factory(1, RuntimeError("配额超限"), attempts),
    )

    async def scenario():
        async with connect_live():
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(scenario())
    assert len(attempts) == 1


def test_midsession_oserror_not_retried(monkeypatch):
    # 会话中途的网络错（yield 之后）必须原样上抛——重试只许发生在建链阶段
    attempts: list = []

    @asynccontextmanager
    async def fake_connect_once():
        attempts.append(1)
        yield "session"

    monkeypatch.setattr(client_module, "_connect_once", fake_connect_once)

    async def scenario():
        async with connect_live():
            raise ConnectionResetError("会话中途断了")

    with pytest.raises(ConnectionResetError):
        asyncio.run(scenario())
    assert len(attempts) == 1              # 没有因 body 异常偷偷重连
