# TODO / 进度跟踪

> 跨会话的唯一进度真相源。**开工先读本文件**对齐进度，**收工更新**勾选已完成项、记一行进度日志。状态：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成；行尾 `done` = 旧版任务已完成。
> 阶段与时长参考 `docs/PRD.md` §5「交付计划与降级」；接口与数据模型 `docs/SCHEMA.md` §5–§7；前端设计 `docs/FRONTEND.md`；模式细节 `docs/IELTS.md` / `docs/SCENARIO.md`。
> **前端分轨**：前端各项的**实现**由用户在 `TODO.frontend.md` 单独跟踪；本文件侧对前端项做**功能验证**，两者通过后方可勾选。联调契约见 `docs/FRONTEND_HANDOFF.md`。


## 阶段任务

### P0 骨架（~1.5h）
- [x] 仓库初始化 / uv + pyproject / .env.example done
- [x] Gemini Live "hello" 单次语音往返（`gemini_live.py`） done
- [x] FastAPI 后端骨架 done
- [x] SQLite 初始化 + 表结构（sessions / turns / reports） done
- [x] React 前端骨架（实现归 `TODO.frontend.md`；此处勾选 = 功能验证 + code review 通过）——2026-06-06 验证：功能 PASS；review findings（🔴C1 recorder 泄漏 / 🔴C2 toFixed null / 🟡W1 AbortController / 🟡W4 mode 串 pin / 🟡W5 detail [object Object] / 🟡W6 48k 主路径测试）已全部修复，复审 **PASS**（vitest 42 绿 + build + lint 过）

### P1 评测流水线 ★（~6h，护城河）
- [x] faster-whisper 切片转写（词级时间戳） done
- [x] 客观信号计算（语速 / 停顿 / 填充词 / 自我更正 / 词汇，可单测、确定性） done
- [x] 结构化 judge（注入 descriptor / case prompt，temperature=0） done
- [x] 诊断层 + 雅思四维聚合 → 完整报告 JSON done
- [x] `band_descriptors.md`（官方 descriptor，运行时注入） done
- [x] **增量流水线改造**：逐回合 / 逐题后台转写 + 信号（会话内执行），课后只剩一次 judge 调用 → 报告 ≤5s（SCHEMA §3）——2026-06-06 `ingest_clip` + `finalize_session` + `merge_transcripts`，turns 表存切片级转写
- [x] 切片预上传 Files API；judge 只喂 2–3 段最长用户切片判发音——`upload_clip`（失败降级 inline bytes）+ `select_pronunciation_clips`，真冒烟 file_uri 落库验证
- [x] 后端回填字段收口：`vocabulary_diversity_pct`（TTR）由后端计算填入，judge schema 移除（practice_summary 已回填）——`JudgeReport`/`JudgeDiagnostics` 收口，对前端 Report shape 不变
- [x] `error_rate` 计算落库（judge frequent_errors 总次数 / 转写百词）——空转写为 NULL

### P2 实时对话 ★（~5h）
- [ ] WS 代理 Live（代码完成 + review PASS + 真冒烟通过；在 `feature/live-ws-proxy` 分支未提交，PR 挂起等联调重点 case 测完）
- [ ] 事件转发补全：`interrupted` / `turn_complete`（barge-in 前端清播放队列）+ 建链 `session_started {session_id}`（契约 FRONTEND §5）
- [ ] /ws/live 连接参数：`mode=ielts_a|scenario & case & turn=ptt|natural`；`end_session` 自动触发 judge
- [ ] AudioWorklet → 16k 上传 → Live → 24k 播放（前端 F6 + 联调）
- [ ] PTT + 轮次结束
- [ ] 用户音频 tee + 帧时间戳（供回合切片，喂增量流水线）
- [ ] 延迟徽章（PTT 以 turn_end 为准；自然模式最后非静音帧近似）

### P3 雅思方式 A（~3h）
- [ ] 后端状态机 + 导演方括号提示（`app/live/director.py`）
- [ ] P2 子状态（准备 60s 输入暂停 / 长谈 / 追问）
- [ ] cue card 静态库（8–10 张，并入 `data/questions.json` p2）
- [ ] 前端浮层：cue card + 倒计时 + 笔记 + "我准备好了"

### P4 方式 B + 模式选择（~1.5h）
- [ ] 数据模型升级：`settings` 表（target_band）+ `sessions.is_seed` + status 枚举（SCHEMA §5.1）
- [ ] 会话化接口：`POST /sessions` → 逐题 `POST /sessions/{id}/recordings` → `POST /sessions/{id}/review`（Get Review 触发 judge）→ `DELETE /sessions/{id}`（Give Up 物理删除）；取代旧一次性 `POST /recordings`（SCHEMA §6.2）
- [ ] judge 按 sub_mode 区分：方式 B 注入 descriptor 按 Part 侧重诊断（含发音），**不出数字 band**（dimensions / overall_band 置空）
- [ ] 静态题库 `data/questions.json`（p1/p2/p3 多题）+ `GET /questions?part=`
- [ ] Gemini TTS 预生成题库音频 + `/static/tts` 挂载
- [ ] 三 Part 录音模块：多题流程（TTS 读题 → 录音 → Next 逐题；按钮 Pause/Resume、Next、Get Review、Give Up）
- [ ] 雅思 A/B 选择页（验证 + review）

### P5 情景对话 case（~1.5h）
- [ ] 接入 Live 会话页（复用 P2 代理；无状态机；手动 End + persona 自然收尾；Live 挂直接报错）
- [ ] 点餐 persona prompt + judge prompt
- [ ] 会议 persona prompt + judge prompt
- [ ] ask_help 破壁：控制事件 → 导演提示注入，persona 临时破壁后回角色（方式 A 隐藏按钮）
- [ ] case 选择页（验证 + review）

### P6 报告 + 进步 UI（~4h）
- [ ] 顶部导航 TopNav：Practice（hover 下拉 IELTS/Scenario）/ Library / Review；会话 / 录音中隐藏
- [ ] 首页两块改造（块1 产品介绍 + 块2 ModeSelect）+ `/practice` 页（复用 ModeSelect）
- [ ] 报告页合并：处理态（流水线进度 + 骨架）+ 报告态（流式填充）同一路由 `/report/{id}`；删除独立 Processing 页
- [ ] Library 页 + `GET /sessions` 列表接口（seed 标注"演示数据"）
- [ ] Review 进步面板（原 Progress 改名）：band 轨迹（仅雅思 A）+ 雷达 + 流利度趋势 + 目标差距；`GET /progress` + `GET/PUT /settings`
- [ ] seed 脚本（6–8 条历史会话，`is_seed` 标注；流利度爬升 + 雅思 A band 5.5→6.5）

### P7 eval + 收尾（~2h）
- [ ] eval harness 跑方差（同输入 judge 5 次，四维 band 方差 ≤ 0.5）
- [ ] golden 录音校方向
- [ ] 缺口③：ASR 规范化致 evidence 非 transcript 逐字子串（报告 UI 高亮 / 引证校验）
- [ ] dev-only「跳到下一 Part」
- [ ] README

### P8 缓冲（~1.5h）
- [ ] 端到端联调 / 修复 / 备演示路径

### 拓展（最后优化，不在 24h 主线）
- [ ] 雅思原题库：`ielts_questions` 表 + 录入/查询/删除接口；`GET /questions` 优先原题库、回退静态库（SCHEMA §7）
- [ ] SSE 流式报告 `GET /reports/{id}/stream`（报告态逐段填充；未实现前轮询兜底）

## 进度日志

> 每次收工追加一行：`YYYY-MM-DD — 做了什么 / 卡在哪 / 下次从哪开始`。

2026-06-06 — P0 全部完成并勾选：后端四项复验（pytest 61 绿 / FastAPI 冒烟 /health OK / SQLite 三表齐 / gemini_live.py 完好）；前端骨架 review findings C1/C2/W1/W4/W5/W6 修复（vitest 42 绿 + build + lint），code-reviewer 复审 PASS；统一 PR 提交 / 无阻塞 / 下次从 P1 增量流水线或 P2 事件转发补全开始
2026-06-06 — P1 全部完成并勾选：增量流水线（ingest_clip/finalize_session/merge_transcripts + turns 落转写）、Files API 预上传 + 2–3 段最长切片、JudgeReport schema 收口（TTR 后端回填）、error_rate 落库；pytest 78 绿 + 真冒烟（真 whisper/Gemini/Files API，band 聚合·planted 错误·file_uri·error_rate 全验证）+ review PASS / 无阻塞 / 下次从 P2 事件转发补全（interrupted/turn_complete/session_started）开始


