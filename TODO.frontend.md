# TODO.frontend — 前端并行开发跟踪

> 与后端 **并行** 的前端进度真相源（原 `TODO.md` 不动）。开工先读本文件对齐，收工勾选 + 记一行日志。
> 状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成。（旧版 `done` 标记行已于 2026-06-06 清理：仍准确的勾 `[x]`，被新版取代的已删，历史见进度日志。）
> 契约依据：`docs/FRONTEND.md`（页面树 / 页面明细 / 实时交互 / UI 规则 / 事件契约）、`docs/SCHEMA.md` §5.2（报告 schema）+ §6（全量 API）、`docs/IELTS.md` / `docs/SCENARIO.md`（模式流程）；后端真相源 `app/report.py`、`app/api/`。联调材料 `docs/FRONTEND_HANDOFF.md`。

## 🚫 硬规则：严禁任何后端修改

**本前端工作流的全部任务，只允许新增/修改前端文件，严格禁止改动任何后端代码。** 违反即停。

- 禁止编辑/新增/删除：`app/**`（含 `app/api/`、`app/report.py`、`app/judge/`、`schema.sql`…）、`main.py`、`gemini_live.py`、`pyproject.toml`、`uv.lock`、`tests/**`、`.env*`、`docs/**`、原 `TODO.md`。
- 禁止：新增/改任何 API 端点、改 `Report` schema、改 DB 表结构、写 migration、动 CORS/依赖。
- 后端被当作**只读契约**：端点不存在就视为「该功能 backend-blocked」，前端只对 mock 做，**不得自己去后端补**。需要后端配合的，记成阻塞项交给后端工作流，不在此处动手。
- 前端代码全部收敛在 `frontend/`，不与后端文件路径交叉。

## UI 约定（对齐 FRONTEND.md §4）

- **按钮与导航一律简洁英文**：导航选项卡 Practice / Library / Review；按钮 Next / Pause / Get Review / Give Up / End…（2026-06-06 用户更新，覆盖旧"导航/按钮中文"约定）。
- **章节标题中文、评分术语保留英文**（2026-06-07 用户确认，handoff 013，覆盖 2026-06-06「章节术语一律英文」旧约定）：章节标题中文（练习概况 / 综合分析 / 高频错误 / 优先改进项 / 改写示范 / 总结…，混排如「Fossilization 与自我更正」）；评分术语英文原文（四维 Fluency & Coherence… / IELTS Band Scores / Overall Band / Fossilization）；severity 徽章（high/medium/low）是数据枚举不翻译。**解释性正文保持中文**（由 judge 数据决定，前端不管）。

## 契约锚（按 SCHEMA §6 更新）

| 锚点 | 状态 | 解锁了什么 |
|---|---|---|
| `Report` pydantic schema（`app/report.py`） | **已冻结**（`vocabulary_diversity_pct` 等改后端回填，shape 不变） | 报告渲染对 fixture 独立开发，零等待 |
| 旧 `POST /recordings` | **已移除（PR #17）**，会话化接口取代 | 前端无引用（`api.js` 的 createRecording 已死代码可删） |
| 会话化接口 `POST /sessions` → 逐题 recordings → `/review`、`DELETE` | **已实装并联调通过（PR #17，handoff 004-mode-b）** | F3 真闭环：默认真接口，mock 退居 `VITE_SESSIONS_API=mock` |
| `GET /sessions`（Library）/ `GET /progress` + `GET/PUT /settings`（Review） | **已实装并联调通过（PR #22，handoff 007）**：/sessions 多 `status` 字段、fluency 多 `error_rate` | F5 两页直接对真接口落地；seed 标注逻辑就绪等 seed 脚本 |
| `GET /questions?part=` + `/static/tts` | **已实装并联调通过（PR #15/#19）**：每 Part 8 题 + 24 题预生成 TTS | F3 真题库 + 音频朗读；vite `/static` 代理已接 |
| WS `/ws/live` 契约（FRONTEND §5） | **已上 main（PR #11 + #14 + #20）**：session_started / transcript_delta / interrupted / turn_complete / error / latency_ms / part_change / present_cue_card / start_prep_timer + `ready` 控制全实装；examiner_speaking 仍未发（前端音频帧近似） | F6 主链路（001）+ PTT/徽章（004）+ 导演/P2 浮层（005）联调通过；done 事件待后端修模型抢戏 |
| `GET /reports/{id}` status 枚举（SCHEMA §5.1） | **后端 PR #16 迁移**：`done→completed`、`recording→live`（未投 handoff，联调发现） | polling.js 两代兼容（completed/live 入 pin），后端回滚也不挂 |
| `teaching` 下行事件 + `nudge` 上行控制（仅 scenario） | **已上 main（PR #29/#30，handoff 010/011）**：teaching shape = case/kind/chinese/english/example；nudge = `{"type":"nudge","stage":1\|2\|3}`（后端 8s 防抖 + 钳制，方式 A 发了也忽略） | F7 求助卡片 + 沉默分级探询计时器 |

## 任务

### F0 · 脚手架
- [x] Vite + React + Router + recharts；fetch 封装（`lib/api.js`，`/api` 代理）；路由壳（后经 F1 路由重构）
- [x] 共享 PCM/WAV 编码 util（`lib/audio/`：wavEncoder + pcmWorkletProcessor + recorder；vitest 过）
- [x] **修复 code review findings**：🔴C1 recorder `start()` 半途失败泄漏 mic/AudioContext、🔴C2 ReportView `overall_band.toFixed` null 防御；🟡W1 轮询 AbortController / W4 mode 串 pin / W5 detail [object Object] / W6 wavEncoder 48k→16k 主路径测试。——2026-06-06 后端 session 代修（用户 /goal「完成 P0」指令）+ code-reviewer 复审 PASS（vitest 42 绿），根 TODO P0 已勾；遗留小项：`routes/Processing.jsx` 已成死代码（轮询并入 Report.jsx），随 F1 路由重构删除

### F1 · 导航与页面骨架（新设计，零后端依赖）
- [x] **TopNav**：Practice（hover 下拉 IELTS / Scenario，直达下一级）/ Library / Review；**实时会话 / 录音进行中隐藏**（`/live` `/record` 整栏隐藏），只留 End / Give Up 出口
- [x] **首页两块改造**：块1 产品介绍（hero）+ 块2 ModeSelect（抽组件 `components/ModeSelect.jsx`）
- [x] **`/practice` 页**：复用 ModeSelect；hover 下拉可跳过本页
- [x] **路由重构**：`Progress.jsx` 改名 `Review.jsx`（`/review`，旧 `/progress` 加跳转）；删除 `Processing.jsx` 独立路由（并入 F2，旧 `/processing/:id` 跳 `/report/:id`）；新增 `/library`；`Placeholder.jsx` 暂留（Live/Library/Review 仍占位，随 F5/F6 真页面落地再删）
- [x] **偏差修正**：情景对话从录音页切到实时会话页（旧 F1 按废弃架构接了录音页；路由已指向 `/live?mode=scenario&case=`，会话页本体在 F6）

### F2 · 报告页 ★
- [x] 对 fixture 渲染全部 8 段 + recharts 雷达 + 情景隐藏 band 区 + unscorable 分支（`/report/demo-*` 零后端预览）
- [x] **处理态并入**：`/report/{id}` 单路由双状态——未就绪显示流水线进度（按 `GET /reports` 的 `status`+`stage`: transcribe/signals/judge，stage 缺失降级整体文案）+ 报告骨架，就绪切报告态；原 F4 轮询逻辑（`lib/polling.js`）迁入；Library 进入直接报告态不闪处理态（loading 阶段只出中性骨架）
- [x] 方式 B 报告适配：无 band（dimensions/overall 置空）但有 descriptor 对齐诊断——已确认与情景共用"无 band"渲染分支（`isIelts` 判 dimensions+overall 非空），与 unscorable（`unscorable===true`）互不混淆，`report.test.js` 有 pin（IELTS.md §3 / SCENARIO.md §3）

### F3 · 录音页（方式 B，多题是 docs 唯一形态）

> 2026-06-06 校准（用户拍板）：**不存在"单题模式"**——IELTS.md §3 / FRONTEND.md §2 只定义多题流程。现有单题页（`Record.jsx`，`POST /recordings` 闭环）是偏离 docs 的旧脚手架，多题页落地时**直接替换删除**，不并存、不保留。

- [x] **多题录音页**（IELTS.md §3，已替换 `Record.jsx`）：一个 Part 多题；题目文字呈现 + TTS 朗读，**朗读结束自动进入录音**（题库音频就绪前：本地静态题库 `lib/questions.js` + 浏览器 SpeechSynthesis 兜底，无声环境按词数估时上限不卡死）；录音含电平条；整个 Part 完成出**一份 Part 级报告**（不按题出）
- [x] **控制按钮**（简洁英文，IELTS.md §3）：**Pause/Resume**（AudioContext suspend/resume，暂停不产生静音填充、计时不清零）/ **Next**（保留本题录音逐题上传进下一题）/ 末题 **Get Review** 替代 Next / **Give Up**（直接物理删除回 /ielts，无确认框——2026-06-07 用户拍板去掉）；上传/建会话失败有 Retry（暂存 blob 不重录）
- [x] **接口流转**：`POST /sessions` → 逐题 `POST /sessions/{id}/recordings` → 末题 `POST /sessions/{id}/review`；Give Up = `DELETE /sessions/{id}`——**真后端联调通过（handoff 004-mode-b，PR #17）**：默认走真接口，`VITE_SESSIONS_API=mock` 切离线 mock（Get Review 落 `/report/demo-ielts-b` fixture，零后端可演示）；8 题全流程实测 201→202×8→review→completed→B 报告
- [x] 题目与 TTS 经 `GET /questions?part=` 获取——真接口 + 预生成音频联调通过（每 Part 8 题，`tts_url=/static/tts/{id}.wav` 24k WAV 经 vite `/static` 代理播放，朗读完自动进录音）；朗读兜底链：tts_url → SpeechSynthesis → 估时；离线 mock 回本地静态题库（§6.5 shape pin 不变）
- [x] 附带：`lib/polling.js` 兼容正式契约 status（§6.3 `ready` ≡ `done`，两代并存期后端切契约前端零改动）；新增方式 B fixture `demo-ielts-b`（无 band 有诊断，同时补齐 F2 方式 B 适配的零后端预览）

### F5 · Library + Review（handoff 007 / 后端 PR #22，直接对真接口，mock 阶段跳过）
- [x] **Library 页**（`/library`）：真 `GET /sessions` 列表（时间 / 模式标题 / 时长 / 摘要分 band 优先退 WPM）→ 点进 `/report/{id}`；`is_seed` 标"演示数据"（逻辑就绪，seed 脚本待后端）；failed/processing 打标可点；live/recording 瞬态过滤（51 行真库实测 32 行展示）；空态/加载/错误+Retry 三态
- [x] **Review 进步面板**（`/review`）：真 `GET /progress`——band 轨迹折线（overall 粗线+四维细线，11 点）+ 最新雷达（latest_bands→BandRadar 适配）+ 流利度四小图（wpm/silence_ratio/filler_pm/**error_rate 新增线**，18 点）+ gap 目标差距芯片（正=还差 负=已超绿标）；目标 band 接 `GET/PUT /settings`（0–9 步进 0.5 / null 清除 / 422 中文直出），localStorage 方案废止

### F6 · 实时会话页（后端 WS 已上 main；handoff 001 主链路联调通过）
- [x] WS 接入：`/ws/live?mode=ielts_a|scenario&case&turn`；处理 `session_started`（存 id，End 发 `end_session` 后跳 `/report/{id}`）——真链路实测通过（合成语音→转写→考官回复→End→真 id 报告页）；前端参数校验提前挡非法 mode/缺 case
- [x] AudioWorklet 16k 采集上传（`lib/live.js` 合批 ~200ms 防碎包）+ 24k 播放队列（`lib/audio/player.js`）；**收到 `interrupted` 立即清空播放队列**（flush 含未开播源；实测未触发——需真人插话时机，单测覆盖，待下次联调验证）
- [x] PTT 按钮 + 自然模式开关（连接参数，切换走重连）+ 延迟徽章（自然模式标 ≈ 近似）——handoff 004（后端 PR #14）：按住推帧（onFrame 闸门，松开期不上行）/ 松开**先 flush 合批器再发 turn_end**（时序硬约束）/ `turn_complete` 解锁下一次按键（pttReducer 状态机，vitest pin）/ 开关切换改 URL `turn=` 走重连；真链路联调 PASS——按住期考官 0 应答（说完 3s+ 静默）、ptt 1075/1120ms 精确徽章、natural ≈1444ms、切换重连状态重置、PTT 会话 End→band 4.5 报告闭环
- [x] 双人转写流（transcript_delta 同 role 增量并气泡）+ 考官说话指示——**examiner_speaking 事件后端未发**，以 24k 帧到达近似（帧来亮 / turn_complete 或队列播空灭）
- [x] Part 2 浮层（仅雅思 A，handoff 005 / 后端 PR #20）：p2_prep 期浮层只盖转写区（footer End 可达）= cue card（present_cue_card）+ 60s 倒计时（start_prep_timer，UI 展示不本地切态）+ 笔记 textarea + I'm ready（发 `{"type":"ready"}`，等 part_change p2_talk 收浮层）；p2_talk 显内联 cue card + 笔记；Part 进度条接 part_change（p2_* 合并 Part 2，done → Finished + 提示点 End）；真链路全流程联调 PASS（P1 4 轮→浮层→ready 秒切 p2_talk→P3→End→A 报告 band 4.5 + 雷达）。⚠️ done 事件后端未发成功（模型抢戏提前宣布考试结束，FSM 轮数未满），done UI 仅单测覆盖，待后端修复后补验
- [x] 情景对话同页接入（handoff 006 / 后端 PR #21）：复用 F6 主链路，方式 A 专属 UI（进度条/浮层/倒计时）因事件不发自然隐藏 ✓ 手动 End 唯一结束路径 ✓ Live 挂直接报错（不降级）✓ case 选择页 label 简洁英文（Ordering Food / Work Meeting，scenarioLabel 进 Live 标题）✓ 真链路双 case 联调：ordering 服务员守角色应答 + ≈1257ms 徽章 + End→报告无 band 6 段诊断；meeting 主持守角色冒烟 ✓。**ask_help 已按用户决策移出 24h 主线（006），不做**
- [x] 联调：handoff 001（主链路 + 反例）与 002（修缮验收）双 PASS——**live 全链路真报告闭环**：两轮对话 → End → 处理态流水线 → `done` → 真报告渲染（band 4.5 + 雷达 + 4 维度卡），切片落盘、StrictMode 孤儿清理验证 ✓；001 的 4 条发现后端已全修（PR #12/#13）。余项：barge-in `interrupted` 真人插话时机 + 2s 回补听感（headless 无法验，待手动）；`docs/FRONTEND_HANDOFF.md`（A1–G6）仍不存在，B2 长独白断轮 / C4 重连未测

### F7 · 情景对话增强（handoff 010/011，后端 PR #29/#30 已合 main）

- [ ] **teaching 求助卡片**（handoff 010 / PR #29）：scenario 会话页接新 WS 事件 `teaching`（`{type, case, kind: mixed_cn|full_sentence_cn|explicit_ask, chinese, english, example}`，一轮 0..n 条通常 ≤1，仅 scenario 发）→ 转写流内插**求助卡片**：主体 `chinese → english` + 副行例句，样式区别于对话气泡（教练侧征非对话内容）；kind 小角标（Mixed / Stuck / Phrase）可选；`case` 字段冗余可忽略；方式 A 页面零改动（永不收到）；`live.test.js` pin 事件 shape。自测：ordering 说 "I want to order 意大利面" 出卡片 + 模型 recast；meeting "落后 on the schedule" → behind schedule 职场译法；整句中文 → kind=full_sentence_cn 模型等复述；90s 内第 3 次求助模型口头鼓励但卡片照出
- [x] **沉默计时器分级 nudge**（handoff 011 / PR #30，PASS 已归档）：`lib/nudge.js` 计时器状态机（13 组 vitest pin）+ Live.jsx 挂载（仅 scenario）——起点 turn_complete + player 排空双条件；人声重置 = 连续 30 帧 ≈80ms RMS ≥ 500/9000（单帧爆音/底噪不触发），重置阶梯且话音落点重起；AI 播音暂停不清阶梯（nudge 语音不打断升级链）；teaching 全量重置；PTT 取 cap stage 1 **且** 20s 翻倍双保险；End 即停表。真链路：natural 三级（10s 轻提示→12s 句头→15s 两选项语音逐级对应）+ PTT 单级不升级 + 满幅假 mic 反例 0 探询全 PASS。留真人："Let's pause" C5 互斥、阈值手感；correction 事件是否重置已写回执问后端

### F8 · 报告页语言与结构（handoff 013/014，后端 PR #34/#35 已合 main）

- [x] **标签中文化**（handoff 013，PASS 已归档）：ReportView.jsx 章节标题中文（练习概况/综合分析/高频错误/优先改进项/快速修正/改写示范/原句/改写/理由），评分术语保留英文（IELTS Band Scores / Overall Band / Fossilization / 四维 label / severity 徽章不动）；report.js 注释同步新约定
- [x] **情景报告结构**（handoff 014，PASS 已归档）：改写示范按内容显隐（rewrites 空列表整节不渲染，`?.length` 防 undefined；unscorable 同受益）+ 末尾「总结」节（summary truthy 才出，雅思恒 null）；fixtures 对齐 shape（scenario 加 summary + rewrites:[]，其余显式 summary:null）+ report.test.js 3 组 pin；真数据 seed-02 渲染验证（seed 已重跑）

## 风险点

| # | 风险 | 对冲 |
|---|---|---|
| R1 | ~~WS 新增事件后端未实现~~ 已解决：PR #11 全实装并联调通过 | 余量：examiner_speaking/part_change 未发（前端以音频帧近似/忽略，前向兼容） |
| R2 | 浏览器拿不到 16k/16-bit/mono PCM | 已解决：`lib/audio/` 共享 util（降采样 + WAV 头） |
| R3 | F3 多题 / F5 数据接口后端未实现 | 契约已定（SCHEMA §6），mock 严格按契约 shape 写，上线即换 |
| R4 | 处理态步骤粒度 | 契约已含 `stage`（transcribe/signals/judge），可做真分步进度，不再降级 spinner |
| R5 | 同目录并行互踩 | 不开 worktree；「🚫 禁改后端」硬规则 + 前端收敛 `frontend/` |
| R6 | `Report` schema 漂移 | 当冻结契约；`vocabulary_diversity_pct` 改后端回填不改 shape；变更走显式同步 |
| R7 | 路由重构（删 Processing、Progress→Review）断内链 | F1 路由重构一次做完 + 全路由目检；旧 `/processing/:id` 加跳转兜底 |

## 排程建议

零后端依赖先行：**F0 修 review findings → F1 导航/页面骨架（TopNav + 首页两块 + /practice + 路由重构）→ F2 处理态并入（轮询已有）→ F3 多题录音页（UI + mock 零后端可做，docs 唯一形态）→ F5 对 mock**；F6 等 `feature/live-ws-proxy` 联调窗口。（原"旧 HTTP 闭环保持可演示"已废止——单题页非 docs 需求，多题页落地即删；真闭环等 P4 会话化接口。）

## 进度日志

> 每次收工追加一行：`YYYY-MM-DD — 做了什么 / 卡在哪 / 下次从哪开始`。

- 2026-06-07 — handoff 013+014 合轮完成（PASS 已归档，同改 ReportView.jsx 统一目检）：013 章节标题中文化（评分术语/severity 徽章保留英文，「UI 约定」段已更新覆盖旧约定）+ 014 改写示范按内容显隐 & 末尾「总结」节 + fixtures shape 对齐（显式 summary:null 防 undefined 分叉，3 组新 pin）。vitest 123 绿 + eslint 0 + build 过；四 fixture headless 逐节断言 + 截图目检（中英混排不挤）+ 真数据 seed-02（总结真文本/无改写示范——后端已重跑 seed）。无阻塞 / 余：inbox 剩 010（teaching 卡片）+ 012（correction 卡片）等用户风险讨论（卡片可见性 vs 默认波形视图）、015（live_feedback 报告区）新件未动。
- 2026-06-07 — handoff 011 完成（PASS 已归档，用户指定顺序 011→013/014，010/012 待风险讨论）：沉默分级 nudge——`lib/nudge.js` 状态机（armed=turn_complete、播音暂停不清阶梯、人声 80ms 连续帧重置、PTT cap1+20s、End 停表）+ Live.jsx 挂载（teaching 事件先消费重置语义，卡片 UI 留 010）。真链路：natural 三级语音逐级对应（10s "No rush…"→12s 句头→15s 两选项）、PTT 20s 单级、440Hz 假 mic 反例 0 探询。vitest 120 绿 + eslint 0 + build 过。坑：headless 隐藏页 >5min Chromium intensive throttling 钳定时器到分钟级（真前台无此事）——联调被坑两轮；假 mic 必须无源 MediaStreamDestination（createConstantSourceNode 是不存在的 API，ternary 落 oscillator 满幅尖叫）。留真人：C5 互斥、阈值手感 / 无阻塞 / 下次：013+014 合轮（同改 ReportView.jsx；PR #34/#35 已合 main 契约就绪）；015 新件已入箱未动。：inbox 两件新交接件入册为 **F7 两项**——010 teaching 求助卡片（PR #29）+ 011 沉默分级 nudge 计时器（PR #30），契约锚表补 teaching/nudge 行；done/ 已 11 件全 PASS 归档无需清理。注意：当前工作区在后端分支 `feat/scenario-grammar-note` 且 `app/**` 有未提交改动（后端 session 进行中），联调起 :8000 前必须核对进程版本（done/004 教训）/ 无阻塞 / 下次：按序号先做 010（一轮一件）。
- 2026-06-07 — Tailwind 全量重写完成（Batch 0–4，用户多轮确认需求：纯 Tailwind v4 / 原风格精致化 / 单亮色 / 分批截图验收）：App.css 1530 行全删，样式收敛 index.css（@theme token + 7 个组件类）+ JSX utilities；修 preflight 回归 4 处（Review 裸 h2 缩水、Top Priorities 序号、维度卡圆点、prompt-list 圆点）。★新功能：Live 默认隐转写改音频响应波形（VoiceWave 28 条 80ms 采样；考官=player AnalyserNode 电平、用户=麦 RMS，rmsLevel16 抽 lib/audio/level.js 与 Record 共用）+ Transcript 徽章开关切回气泡（转写照常累积）；雅思 B Record 不隐题目仅精致化。真链路验证：EXAMINER 波形随播放音量起伏、切气泡转写完整、Record 8 题流程 Q1 录音计时电平正常。vitest 107 绿（player+7 / level 新 4）+ eslint 0 + build 过 / 无阻塞 / 余：barge-in 波形联动与真人听感类仍待手动。

- 2026-06-07 — handoff 009-v2 完成（PASS 归档为 done/009-…-v2.md，防覆盖 round-1 审计）：后端撤回收尾态需求（director 重做为模型驱动，p1_closing/p3_closing 永不下发）——前端清死代码：partStage 两行映射移除、断言改写为「契约外值归 null」防回潮 pin、Live.jsx 注释残留清除；重启 :8000 后建链冒烟过（新开场多问句转写完整）。vitest 107 绿 + eslint 0 + build 过 / 无阻塞 / 余：完整转场时序（语音先于 UI）仍等分支合 main 后补验。
- 2026-06-07 — handoff 009 完成（PASS 已归档）：导演收尾宣告段接入——partStage 补 p1_closing/p3_closing 归并映射（防宣告期进度条闪没）+ live.test.js 两断言；重启 :8000 到分支版本后 ielts_a 建链冒烟过（p1 高亮/考官开场）。vitest 101 绿 + eslint 0 + build 过 / 无阻塞 / 余：完整收尾时序（宣告语音→浮层、宣告期高亮、done）等后端分支合 main 后补验；并行进行中：Tailwind 全量重写 Batch 3 已交验收、Batch 4（Record+Live 沉浸态/波形动效/Transcript 开关）待开工。
- 2026-06-07 — handoff 008 完成（PASS 已归档，纯验证零改动）：seed 数据（PR #23，7 条 16 天铺开）前端全链路验证——Library 39 行 7 条「演示数据」标注自动生效、A 行 band/其余 WPM 如实；Review band 轨迹 5.5→6.0→6.5 爬升段 + 流利度 25 点 seed 段清晰、雷达 latest 按时间序取真实最新（4.5）；seed-04（A 6.0）/seed-02（情景无 band）报告页直接可点开。注记：seed 时间戳 UTC、列表本地时区显示偏一天属设计。007 留的零改动接缝全部兑现 / 无阻塞 / demo 演示数据就绪，前端主线全清。
- 2026-06-07 — handoff 007 完成（PASS 已归档）：F5 两页从占位到实装（mock 阶段跳过直接对真接口）——api.js 增 getSessions/getProgress/getSettings/putSettings + 新建 `lib/sessions.js` 纯函数层（sessionTitle/summaryScore/sessionVisible/statusTag/latestToDimensions/gapRows/FLUENCY_METRICS，13 组 pin）；Library 列表（51 行真库 → 32 行展示，live/recording 瞬态过滤，failed/processing 打标，is_seed 标注逻辑就绪）；Review 面板（band 5 线折线 11 点 / latest_bands 雷达复用 BandRadar / 流利度四小图 18 点含 error_rate / gap 芯片）+ Target Band 表单接 settings（6.5 存→gap +2.0 等出现；6.3→422 中文直出；Clear→null 还原；React 受控 input 注入用 native setter）。坑：小图 Y 轴一位小数把 "100.0" 挤出宽度，改整数刻度。vitest 100 绿 + eslint 0 + build 过 / 无阻塞 / 余：seed 数据等后端脚本（标注逻辑已就绪）、Placeholder.jsx 仅剩 NotFound 在用（保留）。
- 2026-06-07 — handoff 006 完成（PASS 已归档）：情景模式接通——前端改动极小（F6 复用验证为主）：SCENARIO_CASES label 切英文（Ordering Food / Work Meeting，pin 更新）+ scenarioLabel 进 Live 标题。真链路双 case：ordering 完整闭环（服务员迎宾接单守角色 / ≈1257ms 徽章 / End→completed→无 band 6 段诊断报告）；meeting 冒烟（主持确认进度+追问）。方式 A 专属 UI 零事件自然隐藏（部件按事件渲染的设计红利）。ask_help 按 006 移出主线不做——F6 全部完成。vitest 89 绿 + eslint 0 + build 过 / 无阻塞 / 余：F5 Library+Review 对 mock（最后一个未动的页面），方式 A done UI 补验等后端修模型抢戏。
- 2026-06-07 — handoff 005 完成（PASS 已归档）：方式 A 导演前端——`lib/live.js` 增 partStage/PART_STAGES（p2_* 合并，vitest pin 含三个新事件 shape）+ Live.jsx Part 进度条、p2_prep 浮层（cue card + 60s 倒计时 + 笔记 + I'm ready，只盖转写区 End 可达）、p2_talk 内联卡、done 提示 + CSS。真链路全流程：建链即 part_change p1 + 考官开场 → P1 4 轮 → p2_prep 浮层（计时 60→38 实走、4 bullets）→ ready 秒切 p2_talk → P3 → End → A 报告 band 4.5 + 雷达 ✓。🔴 发现后端「模型抢戏」：P3 第 3 轮考官自行宣布考试结束，FSM 轮数未满不发 done——前端 done UI 仅单测覆盖，已写 005 回执；1008 断连 ~7 分钟会话未复现。vitest 88 绿 + eslint 0 + build 过 / 无阻塞 / F6 余：ask_help（仅情景，等后端）+ done UI 补验。
- 2026-06-07 — handoff 004-mode-b 完成（PASS 已归档）：方式 B 真后端接通——sessionApi/questions 默认切真接口（mock 退居 `VITE_SESSIONS_API=mock`，flag 语义反转）、vite 增 `/static` 代理、Record.jsx 题目异步加载（loading/error/Retry）+ 朗读链 tts_url 预生成音频 → SpeechSynthesis → 估时。真链路联调：p1 8 题全流程（201→TTS 206 播放→自动录音→202×8→review→completed）→ B 报告 6 段渲染（dimensions=null 无 band 区、unscorable=false、judge 真诊断含 descriptor 引用）；Give Up DELETE 204 → 回 /ielts。PART_META p1 topic 改 Daily Life（真题库为混合话题）。vitest 84 绿 + eslint 0 + build 过 / 无阻塞 / 余：`api.js` createRecording 死代码待清、409/422 异常分支未实测（前端恒发合法 WAV，UI 不可达）、F5 Library+Review 对 mock。
- 2026-06-07 — 录音页布局调整（用户指令）：Give Up 移出 header 并入操作行（Next/Get Review 右侧；error 态 Retry 旁保留出口）；整页居中——eyebrow/标题/进度/题目卡（卡内文字保持左对齐）/计时电平/按钮行同轴。vitest 81 绿 + eslint 0 + build 过 + 截图目检 + Give Up 直接退出回归 ✓ / 无阻塞。
- 2026-06-07 — Give Up 去确认框（用户指令）：`Record.jsx` 删 `window.confirm`，点击直接物理删除（DELETE /sessions/{id}）回 /ielts；F3 行与页头注释同步。vitest 81 绿 + eslint 0 + build 过 / 无阻塞。
- 2026-06-07 — 排查用户报「PTT 松开即 error」：**非前端 bug**——Gemini 链路（GEMINI_PROXY）间歇抖动；失败时段后端日志 2×1007 Precondition check failed（仅 ptt 连接，疑 setup VAD-off 配置丢损被拒 activity_start）+ 建链 ConnectionReset 群集；链路恢复后 6 轮松开全通（1017–1120ms）。结论已追加 done/004 回执（含给后端的 error 文案建议）；前端按铁律不加自动重连，Retry 兜底已够 / 无阻塞 / 遇到时自查代理节点再 Retry。
- 2026-06-07 — handoff 004 完成（PASS 已归档）：F6 PTT + 延迟徽章实装——`lib/live.js` 增 normalizeTurn / pttReducer（idle→pressed→waiting→turn_complete 解锁）/ formatLatency（ptt 精确、natural 标 ≈）+ Live.jsx 按住推帧闸门、松开先 flush 再 turn_end、turn 开关重连、latency_ms 徽章 + CSS。真链路联调全 PASS（按住期考官 0 应答、ptt 1075/1120ms、natural ≈1444ms、切换重连、PTT 会话报告 band 4.5 闭环）。⚠️ 联调发现后端 PR #16 status 枚举迁移（done→completed / recording→live）未投 handoff 即上线，报告页一度报「未知状态 completed」——polling.js 已两代兼容 + pin，已写 004 回执；流程教训：联调起后端前先核对运行中进程的代码版本（00:50 旧进程无 PTT，首轮测到旧行为）。vitest 81 绿 + eslint 0 + build 过 / 无阻塞 / F6 余：Part 2 浮层、ask_help（等后端事件）+ barge-in/尾音真人听感。
- 2026-06-06 — 前端 session：F1 全完成（TopNav hover 下拉 + `/live` `/record` 沉浸态隐藏顶栏 / ModeSelect 抽组件 / `/practice` / 路由重构含 `/progress`、`/processing/:id` 跳转兜底 / 情景切 `/live`）+ F2 处理态并入单路由（stage 三步流水线 + 骨架 + Library 不闪处理态）+ 按钮文案全切简洁英文；Processing.jsx / Progress.jsx 已删。F0 六项 findings 与后端 session 并行互补完成（W5/W6 后端 session 版本落盘，已交叉核对无互踩；⚠️ R5 实发：同日双 session 并行改 frontend/，动手前必须重读文件）。验证：vitest 42 绿 + eslint 0 + build 过 + headless 全路由冒烟 PASS（唯一 console 502 为后端未起的预期错误分支）/ 无阻塞 / 下次：F5 Library+Review 对 mock（零后端可做），F3 多题 mock 可并行，F6 等 live-ws-proxy 联调窗口。
- 2026-06-06 — 清理旧版 `done` 标记行（用户指令）：仍准确的勾 `[x]`（F0 脚手架×2 / F2 fixture 渲染 / F3 单题录音页，后者描述修正为跳 `/report/{id}`）；被新版取代的删除（F1 旧静态导航流——废弃架构描述、F3 旧处理页轮询——已由 F2 处理态并入行覆盖）；表头 `done` 约定改为清理说明 / 无阻塞 / 下次：F5 对 mock。
- 2026-06-06 — TODO 校准对齐 docs（用户指令）：F3 重写——**单题模式非 docs 需求**（IELTS.md §3 只有多题），撤销刚勾的"单题页 [x] 可演示闭环"行，改为「多题页直接替换删除单题页」；排程废止"旧 HTTP 闭环保持可演示"；多题 UI + mock 零后端可先行，真闭环等 P4 / 无阻塞 / 下次：F3 多题录音页实装。
- 2026-06-07 — handoff 003 验收 PASS（已归档）：F6 分轨验收通过（根 TODO P2 第 4 项后端已勾）；后端代修的 4 项 review findings 逐项核验认可（🟡W1 End 尾音排空——真 bug / W2 Safari 采样率 / W3 player 6 单测 / W4 合批用例），vitest 73 绿复核一致；🔵 ws.onerror 定夺不加（onclose 兜底），Live.jsx 补注释固化 / 无阻塞 / F6 剩余：PTT、Part2 浮层、ask_help（等后端事件）+ barge-in/尾音人耳听感。
- 2026-06-07 — handoff 002 验收 PASS（已归档）：后端修缮（PR #12 tee + #13）后 live 全链路真报告闭环实测通过——两轮合成语音对话 → End → 流水线处理态 → `done` → 真报告（overall 4.5 + 雷达 + 4 维卡）自动渲染；切片 turn000–002 落盘；StrictMode 孤儿无新增。polling.js 契约注释对齐 §6.3 终版。坑：macOS `say` 默认 voice 截断，需 `-v Samantha`。余：barge-in 听感待真人 / 无阻塞 / 下次：F5 对 mock。
- 2026-06-06 — F6 主链路落地（handoff 001，PASS 已归档 done/）：`Live.jsx` 实装（WS 建链/16k 合批上行/24k 播放队列/转写气泡/interrupted flush/error 直出/断连 Retry/End→报告）+ `lib/live.js`、`lib/audio/player.js` + 测试（vitest 66 绿）。真链路实测：`say` 合成语音注入假 mic → Gemini 正确转写 → 考官回复回流 → End 跳真 id 报告。联调发现 🔴 `recording` 过渡态缺契约（前端已兼容并回执后端）。剩余：PTT/Part2 浮层/ask_help 等后端事件、interrupted 真人实测 / 无阻塞 / 下次：F5 对 mock 或等 handoff 002。
- 2026-06-06 — F3 多题录音页落地：`Record.jsx` 整页重写（单题页已替换消失）+ `lib/questions.js`（§6.5 契约 shape 静态题库 + SpeechSynthesis 朗读）+ `lib/sessionApi.js`（§6.2 mock + feature flag）+ recorder 增 pause/resume + polling 兼容 `ready` + 方式 B fixture `demo-ielts-b`。自测：vitest 56 绿（新增 questions/sessionApi 两组契约 pin）+ eslint 0 + build 过 + headless 全流程实测 PASS（Start→读题→自动录音→Pause/Resume→Next×2→末题 Get Review→落报告；Give Up confirm→物理删除→回 /ielts；无 mic 环境优雅降级 Retry；零 console 错误）。`prompts.js` 暂留（scenario 数据 F6 可能复用，frontend 未入 git 删了即丢）/ 无阻塞 / 下次：F5 Library+Review 对 mock。
