# oral

基于 **Gemini Live API** 的最简实时语音对话 demo：用本机麦克风说话 → 流式发送给 Gemini → 实时播放它的语音回复。运行后直接对着麦克风说话即可，`Ctrl+C` 退出。

## 环境要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)（包管理）
- PortAudio（`pyaudio` 的系统依赖）

安装 PortAudio：

```bash
# macOS
brew install portaudio

# Ubuntu / Debian
sudo apt install portaudio19-dev
```

## 安装

```bash
uv sync
```

## 配置

需要一个 Gemini API Key。复制示例文件并填入你自己的 key：

```bash
cp .env.example .env
# 然后编辑 .env，填入 GEMINI_API_KEY
```

或直接在 shell 里 export：

```bash
export GEMINI_API_KEY="你的key"
```

### 代理（可选）

Live API 走 WebSocket。脚本默认尝试本机代理 `http://127.0.0.1:7897`（Clash/Mihomo 混合端口），可用环境变量覆盖：

```bash
export GEMINI_PROXY="http://127.0.0.1:7897"   # 指定代理
export GEMINI_PROXY="none"                      # 关闭代理，直连
```

## 运行

```bash
uv run gemini_live.py
```

看到 `✅ 会话已建立` 后即可对着麦克风说话。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `gemini_live.py` | 语音对话主程序 |
| `main.py` | 占位入口 |
| `pyproject.toml` | 项目与依赖定义 |
| `PR.md` | 本仓库的 PR 提交规范 |
