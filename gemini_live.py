"""
Gemini Live API 最简语音对话 demo
---------------------------------
功能：用本机麦克风说话 -> 流式发送给 Gemini -> 实时播放它的语音回复。
运行后直接对着麦克风说话即可，Ctrl+C 退出。

依赖：
    pip install google-genai pyaudio

  - macOS 装 pyaudio 前先: brew install portaudio
  - Ubuntu/Debian:        sudo apt install portaudio19-dev && pip install pyaudio
  - Windows:              pip install pyaudio  (一般可直接装)

API Key（任选其一）：
    export GEMINI_API_KEY="你的key"     # 推荐，下面代码会自动读取
  或直接把下面 api_key= 那行改成你的 key 字符串。
"""

import asyncio
import os

# ---- 代理设置 ----
# Live API 走 WebSocket，由 websockets 库读取 *_PROXY 环境变量来决定是否走代理。
# 如果不在脚本里固定，仅靠当前 shell 是否 export 了 HTTPS_PROXY，会出现两种坑：
#   1) shell 没 export（如从 IDE/启动器直接运行）时，websockets 会回退到 macOS
#      系统里的 SOCKS 代理，从而报 “requires python-socks” 而连不上；
#   2) 行为随运行环境漂移，不可控。
# 这里在脚本内统一接管：默认走本机 http://127.0.0.1:7897（Clash/Mihomo 混合端口），
# 用 HTTP CONNECT 隧道（无需额外安装 python-socks）。可用环境变量覆盖：
#   export GEMINI_PROXY="http://127.0.0.1:7897"   # 指定代理
#   export GEMINI_PROXY="none"                      # 关闭代理，直连
_proxy = os.environ.get("GEMINI_PROXY")
if _proxy is None:
    _proxy = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        or "http://127.0.0.1:7897"
    )
if _proxy.strip().lower() in ("", "none", "off", "0"):
    # 关闭代理：清掉相关环境变量，避免 websockets 回退到系统 SOCKS 代理
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
               "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(_k, None)
    print("🌐 代理：已关闭（直连）")
else:
    os.environ["HTTP_PROXY"] = _proxy
    os.environ["HTTPS_PROXY"] = _proxy
    print(f"🌐 代理：{_proxy}")

import pyaudio
from google import genai
from google.genai import types

# ---- 音频参数（按 Live API 规范固定）----
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_RATE = 16000      # 麦克风输入：16kHz PCM16
RECV_RATE = 24000      # 模型输出：  24kHz PCM16
CHUNK = 512

MODEL = "gemini-3.1-flash-live-preview"

# 自动从环境变量读取 key；也可改成 api_key="xxx"
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# response_modalities=["AUDIO"] 表示要语音回复
config = {
    "response_modalities": ["AUDIO"],
    # 打开下面两行可以同时拿到双方对话的文字转写，方便调试
    "input_audio_transcription": {},
    "output_audio_transcription": {},
}


async def main():
    pya = pyaudio.PyAudio()

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        print("✅ 会话已建立，开始说话吧（Ctrl+C 退出）...\n")

        # 麦克风输入流
        mic = pya.open(
            format=FORMAT, channels=CHANNELS, rate=SEND_RATE,
            input=True, frames_per_buffer=CHUNK,
        )
        # 扬声器输出流
        speaker = pya.open(
            format=FORMAT, channels=CHANNELS, rate=RECV_RATE, output=True,
        )

        async def send_mic():
            """持续读取麦克风并发给 Gemini"""
            while True:
                data = await asyncio.to_thread(mic.read, CHUNK, exception_on_overflow=False)
                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )

        async def receive_audio():
            """接收 Gemini 的语音并播放"""
            while True:
                async for response in session.receive():
                    # 语音数据
                    if response.data:
                        await asyncio.to_thread(speaker.write, response.data)
                    # 可选：打印文字转写
                    sc = response.server_content
                    if sc:
                        if sc.input_transcription and sc.input_transcription.text:
                            print(f"🧑 你：{sc.input_transcription.text}")
                        if sc.output_transcription and sc.output_transcription.text:
                            print(f"🤖 Gemini：{sc.output_transcription.text}")

        try:
            await asyncio.gather(send_mic(), receive_audio())
        finally:
            mic.stop_stream(); mic.close()
            speaker.stop_stream(); speaker.close()
            pya.terminate()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已退出。")
