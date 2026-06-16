"""connect_live 建链重试单测（_connect_once 打桩，零网络）。

联调实测 Gemini 建链偶发 TLS 被重置（OSError），重连即通——connect_live
只对**建链**失败重试一次；会话中途异常必须原样上抛、绝不偷偷换新会话。
"""

import asyncio
import os
from contextlib import asynccontextmanager

import pytest

from app.live import client as client_module
from app.live.client import connect_live


def _connect_factory(fail_times: int, exc: Exception, attempts: list):
    """返回 _connect_once 替身：前 fail_times 次 __aenter__ 抛 exc，之后成功。"""

    @asynccontextmanager
    async def fake_connect_once(
        turn_mode="natural", system_instruction=None, tools=None, voice=None,
    ):
        attempts.append(turn_mode)
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
        async with connect_live("ptt") as session:
            return session

    assert asyncio.run(scenario()) == "session-2"
    assert attempts == ["ptt", "ptt"]      # turn 模式穿透且重试沿用
    assert "重试一次" in caplog.text


def test_live_config_ptt_disables_vad():
    cfg = client_module._live_config("ptt")
    assert cfg["realtime_input_config"]["automatic_activity_detection"]["disabled"] is True
    # natural 不带该键；模块常量不被污染（深拷贝语义）
    assert "realtime_input_config" not in client_module._live_config("natural")
    assert "realtime_input_config" not in client_module.LIVE_CONFIG


def test_live_config_voice(monkeypatch):
    # 显式 voice → speech_config 注入；不给且 LIVE_VOICE 空 → 不注入（模型默认音色）；
    # LIVE_VOICE 配置非空 → 回落用它；模块常量不被污染
    monkeypatch.setattr(client_module.settings, "live_voice", "")
    cfg = client_module._live_config("natural", voice="Kore")
    assert (
        cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"]
        == "Kore"
    )
    assert "speech_config" not in client_module._live_config("natural")
    monkeypatch.setattr(client_module.settings, "live_voice", "Aoede")
    cfg = client_module._live_config("natural")
    assert (
        cfg["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"]
        == "Aoede"
    )
    assert "speech_config" not in client_module.LIVE_CONFIG


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


_ALL_PROXY_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
    "NO_PROXY", "no_proxy",
)


@pytest.fixture
def clean_proxy_env(monkeypatch):
    """清空全部代理相关环境变量并登记原值（monkeypatch 保证测试后整体还原，
    含被测函数自己写入的 no_proxy=* 也会被回滚，避免串扰其它测试）。"""
    for k in _ALL_PROXY_ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_apply_ws_proxy_env_unset_leaves_env_untouched(clean_proxy_env):
    # None（未配置）→ 完全不碰环境，交给 websockets 自动发现系统/shell 代理
    clean_proxy_env.setattr(client_module.settings, "gemini_proxy", None)
    clean_proxy_env.setenv("HTTP_PROXY", "http://shell:1")
    clean_proxy_env.setenv("no_proxy", "shell-keep")
    client_module._apply_ws_proxy_env()
    assert os.environ["HTTP_PROXY"] == "http://shell:1"
    assert os.environ["no_proxy"] == "shell-keep"


@pytest.mark.parametrize("value", ["none", "off", "", "0", "  None  "])
def test_apply_ws_proxy_env_none_forces_direct(clean_proxy_env, value):
    # none/off → 清掉一切 *_PROXY 并设 no_proxy=*，强制直连（旁路 macOS 系统 SOCKS）
    clean_proxy_env.setattr(client_module.settings, "gemini_proxy", value)
    clean_proxy_env.setenv("HTTPS_PROXY", "http://stale:7897")
    clean_proxy_env.setenv("ALL_PROXY", "socks5://stale:7897")
    client_module._apply_ws_proxy_env()
    for k in client_module._PROXY_ENV_KEYS:
        assert k not in os.environ
    assert os.environ["NO_PROXY"] == "*"
    assert os.environ["no_proxy"] == "*"


def test_apply_ws_proxy_env_explicit_proxy(clean_proxy_env):
    # 指定代理 → 写 HTTP(S)_PROXY，并清掉强制直连态残留的 no_proxy/ALL_PROXY，
    # 防 no_proxy=* 把刚设的代理旁路掉
    clean_proxy_env.setattr(client_module.settings, "gemini_proxy", "http://127.0.0.1:7897")
    clean_proxy_env.setenv("NO_PROXY", "*")
    clean_proxy_env.setenv("ALL_PROXY", "socks5://stale")
    client_module._apply_ws_proxy_env()
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert "NO_PROXY" not in os.environ and "no_proxy" not in os.environ
    assert "ALL_PROXY" not in os.environ and "all_proxy" not in os.environ


def test_midsession_oserror_not_retried(monkeypatch):
    # 会话中途的网络错（yield 之后）必须原样上抛——重试只许发生在建链阶段
    attempts: list = []

    @asynccontextmanager
    async def fake_connect_once(
        turn_mode="natural", system_instruction=None, tools=None, voice=None,
    ):
        attempts.append(turn_mode)
        yield "session"

    monkeypatch.setattr(client_module, "_connect_once", fake_connect_once)

    async def scenario():
        async with connect_live():
            raise ConnectionResetError("会话中途断了")

    with pytest.raises(ConnectionResetError):
        asyncio.run(scenario())
    assert len(attempts) == 1              # 没有因 body 异常偷偷重连
