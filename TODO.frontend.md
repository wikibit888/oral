# TODO.frontend — 前端并行开发跟踪

> 与后端 **并行** 的前端进度真相源（原 `TODO.md` 不动）。开工先读本文件对齐，收工勾选 + 记一行日志。
> 状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成；行尾 `done` = 旧版任务已完成，新版需要更新，更新不考虑历史兼容。
> 契约依据：`docs/FRONTEND.md`（页面树 / 页面明细 / 实时交互 / UI 规则 / 事件契约）、`docs/SCHEMA.md` §5.2（报告 schema）+ §6（全量 API）、`docs/IELTS.md` / `docs/SCENARIO.md`（模式流程）；后端真相源 `app/report.py`、`app/api/`。联调材料 `docs/FRONTEND_HANDOFF.md`。

## 🚫 硬规则：严禁任何后端修改

**本前端工作流的全部任务，只允许新增/修改前端文件，严格禁止改动任何后端代码。** 违反即停。

- 禁止编辑/新增/删除：`app/**`（含 `app/api/`、`app/report.py`、`app/judge/`、`schema.sql`…）、`main.py`、`gemini_live.py`、`pyproject.toml`、`uv.lock`、`tests/**`、`.env*`、`docs/**`、原 `TODO.md`。
- 禁止：新增/改任何 API 端点、改 `Report` schema、改 DB 表结构、写 migration、动 CORS/依赖。
- 后端被当作**只读契约**：端点不存在就视为「该功能 backend-blocked」，前端只对 mock 做，**不得自己去后端补**。需要后端配合的，记成阻塞项交给后端工作流，不在此处动手。
- 前端代码全部收敛在 `frontend/`，不与后端文件路径交叉。

## UI 约定（对齐 FRONTEND.md §4）

- **按钮与导航一律简洁英文**：导航选项卡 Practice / Library / Review；按钮 Next / Pause / Get Review / Give Up / End…（2026-06-06 用户更新，覆盖旧"导航/按钮中文"约定）。
- **评分术语一律英文原文**：维度（Fluency & Coherence / Lexical Resource / Grammatical Range & Accuracy / Pronunciation）、章节（Practice Summary / Analysis / Frequent Errors / Fossilization / Self-Corrections / Top Priorities / Rewrites）、字段标签（Vocabulary Diversity / Quick fix / Original / Rewrite）。**解释性正文保持中文**（由 judge 数据决定，前端不管）。

## 契约锚（按 SCHEMA §6 更新）

| 锚点 | 状态 | 解锁了什么 |
|---|---|---|
| `Report` pydantic schema（`app/report.py`） | **已冻结**（`vocabulary_diversity_pct` 等改后端回填，shape 不变） | 报告渲染对 fixture 独立开发，零等待 |
| 旧 `POST /recordings` / `GET /reports/{id}` | 已实现，但**设计上被会话化接口取代** | 旧录音→报告闭环可真连；新流程等 P4 |
| 会话化接口 `POST /sessions` → 逐题 recordings → `/review`、`DELETE` | **契约已定（SCHEMA §6.2）、后端未实现** | F3 多题改造 backend-blocked，先对 mock |
| `GET /sessions`（Library）/ `GET /progress` + `GET/PUT /settings`（Review） | **契约已定（SCHEMA §6.2/§6.4）、后端未实现** | F5 先对 mock，契约不再是"薄约定"而是正式文档 |
| `GET /questions?part=` + `/static/tts` | **契约已定（SCHEMA §6.5）、后端未实现** | F3 题目/TTS 播放先用本地静态题库顶 |
| WS `/ws/live` 契约（FRONTEND §5） | 基础实现在 `feature/live-ws-proxy`（未合并）；**新增事件 session_started / interrupted / turn_complete 未实现** | F6 按正式契约写，feature flag 后，接受小返工 |

## 任务

### F0 · 脚手架
- [ ] Vite + React + Router + recharts；fetch 封装（`lib/api.js`，`/api` 代理）；路由壳 done
- [ ] 共享 PCM/WAV 编码 util（`lib/audio/`：wavEncoder + pcmWorkletProcessor + recorder；vitest 过） done
- [x] **修复 code review findings**：🔴C1 recorder `start()` 半途失败泄漏 mic/AudioContext、🔴C2 ReportView `overall_band.toFixed` null 防御；🟡W1 轮询 AbortController / W4 mode 串 pin / W5 detail [object Object] / W6 wavEncoder 48k→16k 主路径测试。——2026-06-06 后端 session 代修（用户 /goal「完成 P0」指令）+ code-reviewer 复审 PASS（vitest 42 绿），根 TODO P0 已勾；遗留小项：`routes/Processing.jsx` 已成死代码（轮询并入 Report.jsx），随 F1 路由重构删除

### F1 · 导航与页面骨架（新设计，零后端依赖）
- [ ] 旧静态导航流（首页模式卡 → 雅思 A/B（A 设目标 band）/ 场景 case → 录音页；`lib/modes.js` 契约 pin） done
- [ ] **TopNav**：Practice（hover 下拉 IELTS / Scenario，直达下一级）/ Library / Review；**实时会话 / 录音进行中隐藏**，只留 End / Give Up 出口
- [ ] **首页两块改造**：块1 产品介绍（hero）+ 块2 ModeSelect（抽组件）
- [ ] **`/practice` 页**：复用 ModeSelect；hover 下拉可跳过本页
- [ ] **路由重构**：`Progress.jsx` 改名 `Review.jsx`（`/review`）；删除 `Processing.jsx` 独立路由（并入 F2）；新增 `/library`；删 `Placeholder.jsx`（随真实页面落地）
- [ ] **偏差修正**：情景对话从录音页切到实时会话页（旧 F1 按废弃架构接了录音页；路由先指向，会话页本体在 F6）

### F2 · 报告页 ★
- [ ] 对 fixture 渲染全部 8 段 + recharts 雷达 + 情景隐藏 band 区 + unscorable 分支（`/report/demo-*` 零后端预览） done
- [ ] **处理态并入**：`/report/{id}` 单路由双状态——未就绪显示流水线进度（按 `GET /reports` 的 `status`+`stage`: transcribe/signals/judge）+ 报告骨架，就绪切报告态；原 F4 轮询逻辑（`lib/polling.js`）迁入；Library 进入直接报告态不闪处理态
- [ ] 方式 B 报告适配：无 band（dimensions/overall 置空）但有 descriptor 对齐诊断——确认与情景的"无 band"渲染分支不混淆（IELTS.md §3 / SCENARIO.md §3）

### F3 · 录音页（方式 B 多题改造）
- [ ] 旧单题录音页（getUserMedia → WAV → `POST /recordings` → 跳处理页；题目卡 + 电平条 + 试听/重录） done
- [ ] 旧处理页轮询（`lib/polling.js` 纯函数 + failed/未知/网络错分支） done
- [ ] **多题流程改造**（IELTS.md §3）：一个 Part 多题；TTS 读题（音频就绪前先本地静态题库 + 浏览器兜底）→ 录音 → **Next**（保留本题进下一题）→ 末题 **Get Review** 提交出报告；**Pause/Resume**；**Give Up**（确认框 → 物理删除）
- [ ] **接口切换**：`POST /sessions` → 逐题 `POST /sessions/{id}/recordings` → `POST /sessions/{id}/review` / `DELETE`（backend-blocked：P4 未实现，先对 mock + feature flag）
- [ ] 题目改从 `GET /questions?part=` 取 + TTS 音频播放（backend-blocked）

### F5 · Library + Review
- [ ] **Library 页**（`/library`）：会话列表（时间 / 模式 / 时长 / 摘要分）→ 点进报告页；seed 行标注"演示数据"；对 mock 先做，真数据等 `GET /sessions`
- [ ] **Review 进步面板**（`/review`）：band 轨迹折线（仅雅思 A：四维 + overall）+ 最新雷达 + 流利度趋势（全模式：WPM / 静默比 / 填充词密度）+ 目标差距（target − 各维）；对 mock 先做，真数据等 `GET /progress` + `GET/PUT /settings`（目标 band 迁出 localStorage）

### F6 · 实时会话页（依赖 P2 WS；契约已正式化）
- [ ] WS 接入：`/ws/live?mode=ielts_a|scenario&case&turn`；处理 `session_started`（存 id，End 后跳 `/report/{id}`）
- [ ] AudioWorklet 16k 采集上传 + 24k 播放队列；**收到 `interrupted` 立即清空播放队列**（barge-in 闭环）
- [ ] PTT 按钮 + 自然模式开关（连接参数，切换走重连）+ 延迟徽章（自然模式标注近似值）
- [ ] 双人转写流（transcript_delta）+ 考官说话指示（examiner_speaking / turn_complete）
- [ ] Part 2 浮层（仅雅思 A）：cue card + 60s 倒计时 + 笔记 + "I'm ready"（present_cue_card / start_prep_timer / part_change 事件）
- [ ] 情景对话同页接入：无 Part 进度条；**ask_help 按钮仅情景显示**；手动 End；Live 挂直接报错页（不降级）
- [ ] 联调：按 `docs/FRONTEND_HANDOFF.md` 边际 case（A1–G6）实测，重点 🔴 A1 音频残留 / B2 长独白断轮 / C4 重连

## 风险点

| # | 风险 | 对冲 |
|---|---|---|
| R1 | WS 新增事件（session_started/interrupted/turn_complete）后端未实现 | 契约已正式落 FRONTEND §5；F6 放 feature flag，事件缺失时降级（无 barge-in flush） |
| R2 | 浏览器拿不到 16k/16-bit/mono PCM | 已解决：`lib/audio/` 共享 util（降采样 + WAV 头）done |
| R3 | F3 多题 / F5 数据接口后端未实现 | 契约已定（SCHEMA §6），mock 严格按契约 shape 写，上线即换 |
| R4 | 处理态步骤粒度 | 契约已含 `stage`（transcribe/signals/judge），可做真分步进度，不再降级 spinner |
| R5 | 同目录并行互踩 | 不开 worktree；「🚫 禁改后端」硬规则 + 前端收敛 `frontend/` |
| R6 | `Report` schema 漂移 | 当冻结契约；`vocabulary_diversity_pct` 改后端回填不改 shape；变更走显式同步 |
| R7 | 路由重构（删 Processing、Progress→Review）断内链 | F1 路由重构一次做完 + 全路由目检；旧 `/processing/:id` 加跳转兜底 |

## 排程建议

零后端依赖先行：**F0 修 review findings → F1 导航/页面骨架（TopNav + 首页两块 + /practice + 路由重构）→ F2 处理态并入（轮询已有）→ F5 对 mock**；F3 多题改造等 P4 接口（mock 先行可并）；F6 等 `feature/live-ws-proxy` 联调窗口。改造期间旧 HTTP 闭环（旧 /recordings → 报告）保持可演示。

## 进度日志

> 每次收工追加一行：`YYYY-MM-DD — 做了什么 / 卡在哪 / 下次从哪开始`。
