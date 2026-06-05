# TODO / 进度跟踪

> 跨会话的唯一进度真相源。**开工先读本文件**对齐进度，**收工更新**勾选已完成项、记一行进度日志。状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成。
> 阶段与时长参考 `docs/PRD.md` §10「24 小时施工计划」。

## 里程碑关卡

- [ ] **第 8h 关卡**：产出完整报告 JSON —— 雅思方式 B + 情景对话已端到端可用、不依赖 Live。
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
- [ ] faster-whisper 切片转写（词级时间戳）
- [ ] 客观信号计算（语速 / 停顿 / 填充词 / 自我更正 / 词汇，**可单测、确定性**）
- [ ] 结构化 judge（注入 descriptor / case prompt，temperature=0）
- [ ] 诊断层 + 雅思四维聚合 → 完整报告 JSON
- [ ] `band_descriptors.md`（官方 descriptor，运行时注入）

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
