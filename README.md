# AI 英语口语陪练

本地运行的 AI 口语教练 demo。补在 Duolingo（不练真开口）与真人外教（贵、有压力）之间：零社交压力、随时可用、场景沉浸。陪练为主、考官为辅——**对话中零打断，所有评测课后呈现**。

## 两个模式，一套引擎

评测引擎（whisper 转写 → 客观信号 → 结构化 LLM judge → 报告）完全共享，会话内增量执行，**会话结束 ≤5s 出报告**。模式差异只在 persona prompt、流程、是否出 band。

| 模式 | 流程 | 输出 |
|---|---|---|
| **雅思 · 方式 A 模拟考试** | 实时对话（Live），P1→P2→P3 一气呵成，状态机当导演 | 官方四维 band + 诊断报告 |
| **雅思 · 方式 B 分模块** | 按 Part 录音，一 Part 多题，不依赖 Live | descriptor 对齐的诊断报告，无 band |
| **情景对话**（点餐 / 会议） | 实时对话（Live），可夹中文求助（AI 即时教学）+ 沉默引导，手动 End | 诊断式文字反馈 + 末尾总结，无 band |

报告内容：四维 band（仅雅思，逐字证据 + descriptor 对照）、Common Patterns、Frequent / Fossilized Errors、Self-Corrections、Top Priorities（3–5 条带 severity + Quick Fix）、原句改写（仅雅思）；情景另有会话内反馈实录（语法纠错对照 + 中文求助记录）与末尾总结段。跨会话进步曲线（band 轨迹 / 雷达 / 流利度趋势 / 目标差距）。

## 架构

```
麦克风 (16k PCM)
  ├─ 实时路径（雅思 A + 情景）: 浏览器 ⇄ WS /ws/live ⇄ FastAPI 代理 ⇄ Gemini Live
  │                          └─ tee 用户音频 + 帧时间戳 → 按回合切片
  └─ 录音路径（仅方式 B）: POST /sessions → 逐题上传录音 → Get Review
                         ↓
  评测流水线（三入口共用，会话内增量执行）:
    faster-whisper 词级时间戳 → 客观信号（语速/停顿/填充词/自我更正/词汇，确定性）
    → 结构化 judge（会话结束后一次调用：2–3 段最长切片 + 信号 JSON + transcript
      + 模式 prompt；temperature=0 + 逐字证据 grounding）
    → 报告（+ 四维 band，仅雅思 A）→ 进步曲线（SQLite）
```

两个关键设计：

- **自建客户端包住 Gemini Live**：只有自己代理才能 tee 原始音频流用于评测；本地部署下代理走 localhost，不牺牲亚秒级延迟。

## 技术栈

- **后端**：Python 3.12（uv）、FastAPI、`google-genai` 异步 SDK（Live / judge / TTS）、faster-whisper
- **前端**：React + Vite（图表 recharts）
- **存储**：SQLite，单写死 demo 用户
- **音频**：麦克风入 16kHz/16-bit/mono PCM，Live 出 24kHz PCM，全程零转码；题目 TTS 预生成，运行时零调用

## 快速开始

```bash
uv sync                        # 安装依赖
cp .env.example .env           # 填入 GEMINI_API_KEY（必须）、GEMINI_PROXY（必须）
uv run python -m app.tts       # 预生成题目音频（一次性，雅思的recording模式需要）
uv run python -m app.seed      # 预置 7 条演示历史会话（进步曲线开箱可见）
APP_RELOAD=0 uv run python main.py          # 启动后端 :8000（热重载会掐断 live WS，务必关）
cd frontend && npm install && npm run dev   # 前端 dev server（/api 代理到 :8000）
```

```bash
uv run pytest                  # 后端测试
cd frontend && npm test        # 前端测试
```
> 这是一条补充，由于开发时候的疏忽，代码后端有一个严重的bug，就是必须配置proxy才能使用，本地开发由于直连gemini被限制，始终在proxy环境下进行，忽略了这个问题，也是最后才发现。

## 演示视频

通过网盘分享的文件：题目一口语助手demo演示.mov
链接: https://pan.baidu.com/s/1Fb9YEHHWAeaKQRKio0L2Yg?pwd=f7pn 提取码: f7pn 


## 目录

```
main.py            # 入口
app/               # FastAPI 后端
  api/             # HTTP 路由 + /ws/live WS 代理
  live/            # Live 封装：client / bridge / director(方式A状态机) / tee / help(情景应答台)
  pipeline.py      # 评测流水线编排
  transcribe.py    # faster-whisper 封装
  signals.py       # 客观信号计算
  judge/           # judge prompt / 调用 / band 聚合 / descriptor 数据
  seed.py          # 演示数据预置（python -m app.seed）
frontend/          # React + Vite
data/              # 音频切片 / 题库
tests/             # pytest
```

## To Do

由于时间紧张，雅思部分的题库并没有用到真题，仅锁定部分题型，是本项目后续值得优化的一点

场景对话可支持更多模式

