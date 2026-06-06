# TODO / 进度跟踪

> 跨会话的唯一进度真相源。**开工先读本文件**对齐进度，**收工更新**勾选已完成项、记一行进度日志。状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成。
> 阶段与时长参考 `docs/PRD.md` §10「24 小时施工计划」。

## 里程碑关卡

- [x] **第 8h 关卡**：产出完整报告 JSON —— 雅思方式 B + 情景对话已端到端可用、不依赖 Live。（后端引擎已通；前端录音页 P4 待做）
- [ ] **第 13h 关卡**：实时对话能说能听能转写，否则方式 A 降级 turn-based。

## 阶段任务

### P0 骨架（~1.5h）
- [x] 仓库初始化 / uv + pyproject / .env.example
- [x] Gemini Live "hello" 单次语音往返（`gemini_live.py`）
- [x] FastAPI 后端骨架
- [ ] React 前端骨架
- [x] SQLite 初始化 + 表结构（sessions / turns / reports）

### P1 录音—评流水线 ★（~6h，护城河）
- [x] 录音上传入口（`POST /recordings`，multipart WAV + {mode, sub_mode, scenario_case}）
- [x] faster-whisper 切片转写（词级时间戳）
- [x] 客观信号计算（语速 / 停顿 / 填充词 / 自我更正 / 词汇，**可单测、确定性**）
- [x] 结构化 judge（注入 descriptor / case prompt，temperature=0）
- [x] 诊断层 + 雅思四维聚合 → 完整报告 JSON
- [x] `band_descriptors.md`（官方 descriptor，运行时注入）

### P2 实时对话 ★（~5h）
- [ ] WS 代理 Live
- [ ] AudioWorklet → 16k 上传 → Live → 24k 播放
- [ ] PTT + 轮次结束
- [ ] 用户音频 tee + 帧时间戳（供课后切片）
- [ ] 延迟徽章（用户说完 → 首个回包音频字节）

### P3 雅思方式 A（~3h）
- [ ] 后端状态机 + 导演方括号提示
- [ ] P2 子状态（准备 60s / 长谈 / 追问）
- [ ] cue card 静态库（8–10 张 JSON）
- [ ] 前端浮层：cue card + 倒计时 + 笔记 + "我准备好了"

### P4 方式 B + 模式选择（~1.5h）
- [ ] 三 Part 录音模块（复用状态机单段逻辑）
- [ ] 录音页（题目 + 录音按钮 + 波形 + 提交）
- [ ] 雅思 A/B 选择页

### P5 情景对话 case（~1.5h）
- [ ] 点餐 judge prompt + persona
- [ ] 会议 judge prompt + persona
- [ ] case 选择页

### P6 报告 + 进步 UI（~4h）
- [ ] 诊断式报告页
- [ ] 流利度折线 + 雷达 + 目标差距（recharts）
- [ ] seed 脚本（6–8 条历史会话，标注为演示数据）

### P7 eval + 收尾（~2h）
- [ ] eval harness 跑方差（每维 band std ≤ 0.5）
- [ ] golden 录音校方向
- [ ] dev-only「跳到下一 Part」
- [ ] README

### P8 缓冲（~1.5h）
- [ ] 端到端联调 / 修复 / 备演示路径

## 进度日志

> 每次收工追加一行：`YYYY-MM-DD — 做了什么 / 卡在哪 / 下次从哪开始`。

- 2026-06-06 — 建立 CLAUDE.md 与本 TODO；P0 仅有 Live hello demo，FastAPI/React/SQLite 待起。下次从 P0 后端骨架开始。
- 2026-06-06 — P0 FastAPI 后端骨架完成（`feature/fastapi-skeleton`）：app 工厂 + pydantic-settings 配置 + CORS + `GET /health`、`GET /`；`uv run python main.py` 起服务，自测 /health、/、/docs 均 200。下次做 SQLite 初始化 + 表结构。
- 2026-06-06 — P0 SQLite 初始化 + 表结构完成：`app/schema.sql`（sessions/turns/reports，对齐 PRD §8.1）+ `app/db.py`（get_connection 开外键 / init_db 幂等建表）+ FastAPI lifespan 启动自动建表；`oral.db` 已 gitignore。自测：建表、列名、外键级联删除、CHECK(mode)、report_json 存取全通过。P0 后端就绪，仅剩「React 前端骨架」未做（按 PRD §10 排序，P1 不依赖前端，可先行）。下次按选择：React 骨架，或直接进 P1 录音—评流水线（先做 `POST /recordings` 上传入口）。
- 2026-06-06 — P1 录音上传入口完成：`POST /recordings`（multipart WAV + {mode,sub_mode,scenario_case}）→ 校验（mode/子类一致性 + WAV 头）→ 落盘 `data/audio/{id}.wav` → 建 sessions 行（status=uploaded，duration 由 WAV 头算）。新增 `app/api/recordings.py`、`app/storage.py`、`app/crud.py`，加依赖 python-multipart。自测 6 用例（2 正常 + 4 校验错误）+ 落库/落盘全通过。下次做 P1 第 2 步：faster-whisper 切片转写（词级时间戳）。
- 2026-06-06 — P1 faster-whisper 转写完成（**PR 模式**，分支 `feature/whisper-transcription`）：`app/transcribe.py` 提供 `transcribe(path)→Transcript`（词级时间戳 + 概率 + 语言 + 时长），VAD 关闭以保停顿信号，模型懒加载单例、config 可配（默认 small/cpu/int8/en）。加依赖 faster-whisper。自测：用 macOS say 生成语音转 16k/mono WAV，转写「I think science is mostly about curiosity.」7 词时间戳正确。下次做 P1 第 3 步：客观信号计算（语速/停顿/填充词/自我更正/词汇，可单测、确定性）。
- 2026-06-06 — P1 客观信号计算完成（PR 模式，stacked 分支 `feature/objective-signals`，base=whisper 分支）：抽 `app/models.py`（Word/Transcript）让信号不依赖 ASR；`app/signals.py` 的 `compute_signals(words,duration)` 算语速(gross/articulation)、停顿(0.3s静默/1.0s犹豫/silence_ratio)、填充词密度、自我更正(启发式)、词汇(TTR/低频词(wordfreq)/重复度)，阈值命名常量。`tests/test_signals.py` 3 用例全过（含「同输入两次同输出」确定性断言）。加依赖 wordfreq + dev pytest，pyproject 配 pytest。待 PR #1 合并后本 PR base 自动转 main。下次做 P1 第 4 步：结构化 judge（注入 descriptor/case prompt，temperature=0）。
- 2026-06-06 — P1 judge 第 1 部分完成（PR 模式，分支 `feature/judge-foundation`，base=main）：`app/report.py`（报告 pydantic schema，对齐 PRD §6.2，band 0–9 校验、情景 dimensions/overall 为 None）+ `app/judge/band_descriptors.md`（官方四维 descriptor，运行时注入）+ `app/judge/prompt.py` 的 `build_judge_prompt`（IELTS 注入 descriptor+四维、情景禁 band+case 接入点、grounding 规则=evidence 逐字/防幻觉/信号非成绩）。`tests/test_judge_prompt.py` 8 用例全过（连同信号共 11 个）。不含 LLM 调用、纯单测。下次做 P1 judge 第 2 部分（4b）：Gemini 结构化调用（temperature=0，喂 signals+transcript+音频）+ overall_band 聚合。
- 2026-06-06 — **P1 多 agent 端到端边界测试 + 缺口①修复**（PR #7 已合并 main，分支 `feature/recordings-format-validation`）：派 3 个子 agent 测 P1（HTTP 契约/编排并发/真实音频）。结论：管道/状态机/并发/评分护城河均稳；发现 3 个质量缺口——①音频格式契约零强制（已修）、②不可评输入（静音/外语）judge 拒评但 run_judge 抛错→status=failed 哑失败、用户无报告（待定方案）、③ASR 把 First→1st 致 evidence 非 transcript 逐字子串（留 P7/报告 UI）。本 PR 修①：`POST /recordings` 强制 16k/mono/16bit（_wav_duration_seconds 多读声道/位深 + 0 帧守卫），违约 422；`tests/test_recordings.py` 7 用例。过 code-reviewer（PASS）。`uv run pytest` 49 全过。下次：定缺口②方案，或进 PRD §10 下一阶段。
- 2026-06-06 — **P1 第 5 步完成 + 第 8h 关卡达成**（PR #6 已合并 main，分支 `feature/report-pipeline`）：`app/pipeline.py` 的 `process_session()` 把 transcribe→compute_signals→run_judge→落库串成完整流水线；`POST /recordings` 经 BackgroundTasks 后台触发，`GET /reports/{id}` 轮询契约（done 返完整报告 JSON）。`app/db.py` get_connection 改提交/回滚/关闭上下文管理器（消除轮询连接泄漏）；crud 加 get_session/update_session_status/create_report/get_report。落库铁律：情景四维列 NULL、error_rate 留 NULL（PRD §8.2）。**过 code-reviewer（NEEDS-FIX→修 C1 置 done 移出 try 防误标 failed 屏蔽报告 + W2/W3/W4/W5/S2）**。`uv run pytest` 42 全过（全 mock、临时 DB）。**真端到端冒烟通过**：雅思 P2 22.4s 出报告(overall 6.0+四维逐字 evidence)、情景点餐 24.4s 强制无 band、reports 表正规化列核对无误。下次做 P1 之外的下一阶段：按 PRD §10 可进 P4（方式 B 录音页 / 模式选择，让流水线有前端入口）或 P2 实时对话，或先补 P7 eval harness 压方差。
- 2026-06-06 — P1 judge 第 2 部分（4b）完成（PR 模式，分支 `feature/judge-gemini-call`）：`app/judge/run.py` 的 `run_judge()`——Gemini 结构化调用 temperature=0 + response_schema=Report，雅思喂音频切片判发音、情景强制无 band，practice_summary 用事实值覆盖，overall_band 由 `app/judge/aggregate.py` 四维平均→最近 0.5（round-half-up，避银行家舍入）系统聚合（judge 不自算）。加 config.judge_model（默认 gemini-2.5-flash）。`tests/test_judge_run.py` mock 客户端（temp0/schema/聚合/音频/情景强制无 band/缺四维抛错 + 聚合舍入），全套 30 测全过。**过 code-reviewer 子 agent 审（PASS）**，按 findings 修了：W1 代理改走 http_options 不污染 env + 客户端懒加载单例、W2 parsed 兜底解析失败带上下文、W3 IELTS 无音频 warning、W4 各维 band 对齐 0.5。**真连 Gemini 冒烟通过**（gemini-2.5-flash）：IELTS 带音频返回四维(0.5 半档)+逐字 evidence、overall 由四维聚合(4.75→5.0)；情景强制 dimensions/overall=None、诊断贴合点餐语境。下次做 P1 第 5 步：诊断层+四维聚合串成完整报告流水线（upload→whisper→signals→judge→落库→GET /reports）。
