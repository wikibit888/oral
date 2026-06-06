"""Gemini Live 连接工厂：每个 WS 会话开一条 Live 连接。

代理注意（与 judge 不同）：Live 走 websockets 库，代理**只认 *_PROXY 环境变量**，
judge 用的 httpx `http_options.client_args` 对 WS 不生效。因此这里在连接前按
`settings.gemini_proxy` 显式接管环境变量（无法做到 per-connection，属已知取舍）：
- 设了代理地址 → 导出 HTTP(S)_PROXY；
- 显式 none/off → 清掉相关变量（防 websockets 回退到 macOS 系统 SOCKS 代理，
  报 "requires python-socks"，见 gemini_live.py 顶部注释）；
- 未设置（None）→ 不动环境，由启动 shell 决定。
"""

import copy
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager

from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

# 按 Live API 规范固定：上行 16k PCM16，下行 24k PCM16
SEND_SAMPLE_RATE = 16000
RECV_SAMPLE_RATE = 24000
AUDIO_MIME = f"audio/pcm;rate={SEND_SAMPLE_RATE}"

# 语音回复 + 双向转写（转写喂前端双人转写流，PRD §9 transcript_delta 事件）
LIVE_CONFIG = {
    "response_modalities": ["AUDIO"],
    "input_audio_transcription": {},
    "output_audio_transcription": {},
}

_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)

_live_client: genai.Client | None = None


def _apply_ws_proxy_env() -> None:
    """按 settings.gemini_proxy 接管 websockets 的代理环境变量（见模块 docstring）。"""
    proxy = settings.gemini_proxy
    if proxy is None:
        return
    if proxy.strip().lower() in ("", "none", "off", "0"):
        for k in _PROXY_ENV_KEYS:
            os.environ.pop(k, None)
    else:
        # 只写 HTTP(S)_PROXY：websockets 走 HTTP CONNECT 隧道只认这两个；
        # ALL_PROXY 意味 SOCKS（需额外装 python-socks），故只在清除侧覆盖、不主动写。
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy


def _client() -> genai.Client:
    """懒加载进程内单例（Live 与 judge 各自持有，互不影响）。"""
    global _live_client
    if _live_client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY 未配置，无法建立 Live 会话（检查 .env）。")
        _live_client = genai.Client(api_key=settings.gemini_api_key)
    return _live_client


def _connect_once():
    """返回 SDK 的 Live 连接 context manager（单次尝试，供 connect_live 重试包装）。"""
    _apply_ws_proxy_env()
    # 传防御深拷贝：浅拷贝下嵌套的 *_transcription 子 dict 仍是共享对象，
    # SDK 若原地改动会污染后续所有连接（review W1）
    return _client().aio.live.connect(
        model=settings.live_model, config=copy.deepcopy(LIVE_CONFIG)
    )


@asynccontextmanager
async def connect_live():
    """一条 Live 连接（`async with connect_live() as session:`），建链瞬态失败重试一次。

    联调实测偶发 TLS start_tls 被重置（ConnectionResetError ⊂ OSError），重连即通。
    只重试**建链**（enter_async_context 阶段）：会话中途的异常经 yield 原样上抛，
    绝不偷偷换一条新会话续命——若把 yield 包进 try，body 里的 OSError 也会被
    误捕获触发重连。
    """
    async with AsyncExitStack() as stack:
        try:
            session = await stack.enter_async_context(_connect_once())
        except OSError as e:
            logger.warning("Live 建链瞬态网络错，重试一次：%r", e)
            session = await stack.enter_async_context(_connect_once())
        yield session
