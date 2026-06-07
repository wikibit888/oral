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
- [x] WS 代理 Live（双向音频桥 + 转写事件；review PASS + 真冒烟通过）——2026-06-06 随前三项统一 PR 提交
- [x] 事件转发补全：`interrupted` / `turn_complete`（barge-in 前端清播放队列）+ 建链 `session_started {session_id}`（契约 FRONTEND §5）——真冒烟 turn_complete 真实到达
- [x] /ws/live 连接参数：`mode=ielts_a|scenario & case & turn=ptt|natural`；`end_session` 自动触发 judge——参数校验 + sessions 落库（status=recording）；turn=ptt 仅校验，turn_end 语义归「PTT + 轮次结束」项；tee 未接线前 finalize 无切片落 failed 属预期
- [x] AudioWorklet → 16k 上传 → Live → 24k 播放（前端 F6 + 联调）——2026-06-07 验证：功能 PASS（vitest 73 绿 + lint + build + 前端真链路实测 + 后端两轮真冒烟联调）；review NEEDS-FIX 四警告已修（🟡W1 End 漏 flush 合批尾音→tee 截断 / 🟡W2 Safari 采样率钳制 2 倍速 / 🟡W3 PcmPlayer 零单测 / 🟡W4 合批续推用例），复验 **PASS**
- [x] PTT + 轮次结束——2026-06-07 turn=ptt 关内建 VAD（`_live_config`）；上行首帧自动 activity_start、turn_end 控制→activity_end；真冒烟实锤：发完整段语音 3s 对照窗口考官 0 字节抢答、turn_end 后正常应答
- [x] 用户音频 tee + 帧时间戳（供回合切片，喂增量流水线）——2026-06-06 地板状态机切片（考官开口封片/turn_complete 开新片/interrupted 预缓冲回补）+ 切片即转写预上传，live 会话出真报告；真冒烟 band 6.0 + planted 错误捕获
- [x] 延迟徽章（PTT 以 turn_end 为准；自然模式最后非静音帧近似）——2026-06-07 `LatencyMeter` 相位机 + `latency_ms {value}` 事件（考官首帧、一轮一次）；真冒烟 ptt 894ms / natural 2299ms（VAD 判停耗时，差异符合预期）

### P3 雅思方式 A（~3h）
- [x] 后端状态机 + 导演方括号提示（`app/live/director.py`）——2026-06-07 PR #20：IeltsDirector FSM（预埋式指令 + 音频门控计轮 + 计时器防自取消，5 轮真冒烟迭代实锤）；真 Live 验证至长谈邀请；已知问题：长谈中段偶发上游 1008（当晚服务不稳，记 P8 联调复查）
- [x] P2 子状态（准备 60s 输入暂停 / 长谈 / 追问）——随 PR #20：备题 input_paused 上行丢帧 + 60s 计时器/ready 先到先得 + 追问预埋
- [x] cue card 静态库（8–10 张，并入 `data/questions.json` p2）——2026-06-07 随 PR #15 题库落地（p2×8 张，话题+4 bullets 官方句式）
- [ ] 前端浮层：cue card + 倒计时 + 笔记 + "我准备好了"

### P4 方式 B + 模式选择（~1.5h）
- [x] 数据模型升级：`settings` 表（target_band）+ `sessions.is_seed` + status 枚举（SCHEMA §5.1）——2026-06-07 PR #16：user_version 门控一次性迁移（done→completed/recording→live，防 P4c 后重启误迁）+ settings 单行表 + crud target_band；review C1→修→复审 PASS；**BREAKING：GET /reports status 改名，待统一 handoff 前端**
- [x] 会话化接口：`POST /sessions` → 逐题 `POST /sessions/{id}/recordings` → `POST /sessions/{id}/review`（Get Review 触发 judge）→ `DELETE /sessions/{id}`（Give Up 物理删除）；取代旧一次性 `POST /recordings`（SCHEMA §6.2）——2026-06-07 PR #17：上传/review 竞态关死 + 同题重录去重 + uploaded 死态迁移 v2；149 测 + 真冒烟（双题→38s 报告）；review C1→修→复审 PASS
- [x] judge 按 sub_mode 区分：方式 B 注入 descriptor 按 Part 侧重诊断（含发音），**不出数字 band**（dimensions / overall_band 置空）——2026-06-07 PR #18：MODULE_FOCUS 三 Part 侧重 + B 可评性只看诊断层（对漏填 dims/降级输出鲁棒）；真冒烟 flash-lite 零 band 泄漏；review PASS
- [x] 静态题库 `data/questions.json`（p1/p2/p3 多题）+ `GET /questions?part=`——2026-06-07 PR #15：p1×8/p2×8/p3×8，tts_url 按文件存在性逐请求回填（TTS 落地免重启），/static/tts 挂载随行；review NEEDS-FIX(C1+W1-W5)→全修
- [x] Gemini TTS 预生成题库音频 + `/static/tts` 挂载——2026-06-07 PR #19（挂载已随 #15）：python -m app.tts 增量幂等 + 6.5s 节流贴 10/min 配额 + 429 重试；真跑 24/24 全生成、tts_url 回填 200；review PASS
- [ ] 三 Part 录音模块：多题流程（TTS 读题 → 录音 → Next 逐题；按钮 Pause/Resume、Next、Get Review、Give Up）
- [ ] 雅思 A/B 选择页（验证 + review）

### P5 情景对话 case（~1.5h）
- [ ] 接入 Live 会话页（复用 P2 代理；无状态机；手动 End + persona 自然收尾；Live 挂直接报错）
- [x] 点餐 persona prompt + judge prompt——2026-06-07 PR #21：`app/scenario_cases.py` case 注册表（persona + judge_focus，加 case 只改注册表；白名单推导 + finalize 回填 case_prompt）；真冒烟守角色 + 自然收尾、judge 命中点餐侧重且零 band 泄漏
- [x] 会议 persona prompt + judge prompt——随 PR #21：meeting persona 礼貌质疑追问 blocker、收尾确认行动项，真冒烟过
- [ ] case 选择页（验证 + review）

### P6 报告 + 进步 UI（~4h）
- [ ] 顶部导航 TopNav：Practice（hover 下拉 IELTS/Scenario）/ Library / Review；会话 / 录音中隐藏
- [ ] 首页两块改造（块1 产品介绍 + 块2 ModeSelect）+ `/practice` 页（复用 ModeSelect）
- [ ] 报告页合并：处理态（流水线进度 + 骨架）+ 报告态（流式填充）同一路由 `/report/{id}`；删除独立 Processing 页
- [~] Library 页 + `GET /sessions` 列表接口（seed 标注"演示数据"）——后端接口 2026-06-07 PR #22 完成（倒序 + 摘要分 LEFT JOIN + status/is_seed；契约加 status 字段）；余前端页 + 验证
- [~] Review 进步面板（原 Progress 改名）：band 轨迹（仅雅思 A）+ 雷达 + 流利度趋势 + 目标差距；`GET /progress` + `GET/PUT /settings`——后端接口随 PR #22 完成（band_series 仅方式 A / fluency_series 含 error_rate / gap 正负语义 / 0.5 倍数校验）；余前端面板 + 验证
- [x] seed 脚本（6–8 条历史会话，`is_seed` 标注；流利度爬升 + 雅思 A band 5.5→6.5）——2026-06-07 PR #23：`python -m app.seed` 7 条（A×3 band 5.5→6.0→6.5 真聚合 + B×2 + 情景×2，流利度四指标单调向好）；幂等重插 + --purge 只删 seed 行；report_json 经 Report 模型与真流水线同 schema
- [x] Live 会话 `duration_s` 落库（done/007 反馈①）——2026-06-07 PR #24：end_session 单次回填墙钟时长（单调钟；弃局不回填留 NULL）；存量旧 live 行仍 '—' 属预期

### P7 eval + 收尾（~2h）
- [ ] eval harness 跑方差（同输入 judge 5 次，四维 band 方差 ≤ 0.5）
- [ ] golden 录音校方向
- [ ] 缺口③：ASR 规范化致 evidence 非 transcript 逐字子串（报告 UI 高亮 / 引证校验）
- [ ] dev-only「跳到下一 Part」
- [ ] README

### P8 缓冲（~1.5h）
- [ ] 端到端联调 / 修复 / 备演示路径
- [ ] 方式 A 长谈中段偶发上游 1008 abort 复查（PR #20 已知问题；方向：client_content 与实时音频交错 / 导演提示 turn_complete=False 试探；无导演长会话此前联调正常；done/005 数据点：~7 分钟全程会话未复现）
- [ ] 真库 live 瞬态残留行清理（弃局/StrictMode 累积 17 行；done/007 反馈②；物理删除真数据，方案留用户拍板）

### P9 巡检修复批次（2026-06-07 P0–P6 后端全量巡检，7 子 agent 并行审计产出；按严重级排序，逐项小 PR）

**🔴 demo 前应修**
- [ ] `pyaudio` 移出主依赖（仅 `gemini_live.py` 用；无 portaudio 的机器 `uv sync` 直接构建失败）——`pyproject.toml:12`，移 dev/optional 组 + 文档注明
- [ ] 方式 A「模型抢戏」done 不发（done/005 🔴）：persona 加「禁止自行宣布考试结束」规则 + closing 对策（轮数对齐/检测兜底）——`director.py:27–37,140`；修复后投 handoff 前端补验 done UI
- [ ] `_pick_cue_card` 空题库 IndexError 防护 + 测试（题库损坏时方式 A 入口对用户不透明失败）——`live_ws.py:177`

**🟡 功能隐患**
- [ ] `speaking_time_s` 非负钳制（whisper 时间戳异常可写负值进报告）——`signals.py:86` 一行 `max(0.0, …)`
- [ ] 方式 B 并发 ingest 加 whisper 串行锁（live tee 有 `_ingest_lock`、方式 B 没有，快速连传可并发调 transcribe）——`sessions.py:164`
- [ ] pipeline 落库测试修正：现用 module_p2 mock 绕过剥 band 断言 band 落库（假阳性）；补 exam 真 band + module_p2 无 band 两用例——`test_pipeline.py:110`
- [ ] p2_talk 长谈 2 分钟上限计时器（现全靠模型自觉，不接手则 FSM 卡死）——`director.py`
- [ ] PTT 按住不松直接 End：`activity_open` 悬挂不发 `activity_end`（疑与 done/004 上游 1007 相关）+ 测试——`bridge.py:102`
- [ ] director `_prep_task` 纳入强引用集合 + `_end_prep` 写已关 WS 加 suppress（竞态日志噪音）——`director.py:176,190`
- [ ] Live session 并发写防护（导演 `send_client_content` 与上行 `send_realtime_input` 无锁交错，1008 根因候选）——随 P8 1008 复查一并处理（加锁或 turn_complete=False 探针）
- [ ] `DELETE /sessions` 加状态门或测试钉死「任意状态可删」为设计决策（现 completed/processing 也能物理删除）——`sessions.py:142`
- [ ] scenario 全空诊断标 `unscorable`（对齐方式 B 的 `_diagnostics_empty` 检查，防零反馈 completed 报告）——`run.py:217`
- [ ] 方括号舞台指令下行过滤（模型违规读出时原文直达前端气泡，现纯 persona 软防线）——`bridge.py:174`
- [ ] `GET /progress` series 加 `is_seed` 标注（seed 爬升点与真实点混排，用户会误认演示数据为自己进步；Library 有标注 Review 曲线没有）——`review.py` BandPoint/FluencyPoint + `crud.list_completed_reports`，连带 SCHEMA §6.4 + handoff 前端
- [ ] `.env.example` 补 `APP_RELOAD`（live 联调必关）/ `JUDGE_MODEL`（503 绕行）/ `WHISPER_MODEL` 注释
- [ ] `gemini_live.py` 与 config 对齐：硬编码代理回落 `127.0.0.1:7897` + 不读 `.env`（照 CLAUDE.md 步骤首跑即踩）——`gemini_live.py:33,64`

**🔵 文档漂移 / 低优先**
- [ ] SCHEMA §6.3 status 枚举过期（仍写 done/uploaded，实际 completed/live；两 agent 独立报告）——文档改对齐现实现
- [ ] 契约注记打包：SCHEMA §6.2 `duration_s` 语义分叉（live 墙钟 vs B 录音累加）/ §5.1 漏 `reports.created_at` / SCENARIO.md §4 ask_help 标「已移拓展」/ FRONTEND §5 `examiner_speaking` 加「后端不发，前端音频帧近似」注
- [ ] 小优化打包：`load_band_descriptors` 加 lru_cache（题库有它没有）/ TTS 末题后多睡 6.5s / db.py `_ensure_columns` 对新库是死代码（双真相源加注释）
- [ ] H1 跟踪落地：`signals.py` 停顿计算源头加 TEST.md H1 注释（现仅 pipeline 两处有、源头无）；本条即主 TODO 跟踪锚点

### 拓展（最后优化，不在 24h 主线）
- [ ] 雅思原题库：`ielts_questions` 表 + 录入/查询/删除接口；`GET /questions` 优先原题库、回退静态库（SCHEMA §7）
- [ ] SSE 流式报告 `GET /reports/{id}/stream`（报告态逐段填充；未实现前轮询兜底）
- [ ] ask_help 破壁：控制事件 → 导演提示注入，persona 临时破壁后回角色（方式 A 隐藏按钮；2026-06-07 自 P5 移入——persona 已内置方括号指令规则，接线即用）

## 进度日志

> 每次收工追加一行：`YYYY-MM-DD — 做了什么 / 卡在哪 / 下次从哪开始`。

2026-06-06 — P0 全部完成并勾选：后端四项复验（pytest 61 绿 / FastAPI 冒烟 /health OK / SQLite 三表齐 / gemini_live.py 完好）；前端骨架 review findings C1/C2/W1/W4/W5/W6 修复（vitest 42 绿 + build + lint），code-reviewer 复审 PASS；统一 PR 提交 / 无阻塞 / 下次从 P1 增量流水线或 P2 事件转发补全开始
2026-06-06 — P1 全部完成并勾选：增量流水线（ingest_clip/finalize_session/merge_transcripts + turns 落转写）、Files API 预上传 + 2–3 段最长切片、JudgeReport schema 收口（TTR 后端回填）、error_rate 落库；pytest 78 绿 + 真冒烟（真 whisper/Gemini/Files API，band 聚合·planted 错误·file_uri·error_rate 全验证）+ review PASS / 无阻塞 / 下次从 P2 事件转发补全（interrupted/turn_complete/session_started）开始
2026-06-06 — P2 前三项完成并勾选：WS 代理提交 + interrupted/turn_complete/session_started 事件转发 + 连接参数校验（mode/case/turn ↦ sessions 落库）+ end_session 瞬时调度 finalize（回调在消费控制消息当下建独立 task，不依赖断连后协程存活）；pytest 90 绿 + 真冒烟（真 Live：session_started 首发·双向转写·387KB 下行音频·turn_complete 到达·end_session 后状态离开 recording）+ review PASS（W1/W3/W4/S1-S3 已修）/ 无阻塞 / 下次从 P2 第 4 项（前端 F6 联调）或音频 tee + 帧时间戳开始
2026-06-06 — P2 第 6 项 tee 完成并勾选：UserAudioTee 地板状态机（流位置时钟=字节推导；考官首帧封片 / turn_complete 开新片 / interrupted 2s 预缓冲回补打断起头 / finish 封口闸门防 drain 漏片）+ save_clip 裸 PCM 封 WAV + drain 排干再 finalize；pytest 101 绿 + 真冒烟（live 会话出真报告：band 6.0·planted 主谓错误捕获·turns ts/file_uri 落库·TTR 回填一致）+ review PASS（W1-W4/S1-S3 已修）；期间 judge 上游偶发 503 会直接 failed（无重试，记 P8 缓冲考虑）/ 下次从 F6 联调或 PTT + 轮次结束开始
2026-06-07 — P2 联调修缮（前端 F6 回执 4 条 + judge 503）：end_session 瞬间置 processing（修契约外过渡态）、零切片弃局删孤儿行（StrictMode 双连接）、connect_live 建链 OSError 重试一次（真实 TLS reset 场景验证触发）、judge 上游 5xx 按 (2,5)s 退避重试、APP_RELOAD 可配（联调防热重载杀会话）、SCHEMA §6.3 status 枚举对齐现实现；pytest 110 绿 + 修缮冒烟两项 PASS + review PASS / judge 上游持续高负载时重试耗尽仍诚实 failed / 下次从 F6 功能验证 + review（勾选 P2 第 4 项）或 PTT 开始
2026-06-07 — P2 第 4 项 F6 分轨验收完成并勾选：功能验证 PASS（vitest 73 绿 + lint + build + 前端真链路实测 + 后端两轮真冒烟）；独立 review NEEDS-FIX 四警告（W1 End 漏 flush 合批尾音→tee 截最后一段语音 / W2 Safari 采样率钳制 2 倍速 / W3 PcmPlayer 零单测 / W4 合批续推用例）已按 P0 先例在前端工作树代修，复验 PASS；交接 handoff/inbox/003 待前端 review 后随其轨道提交 / 下次从 PTT + 轮次结束开始
2026-06-07 — **P3 后端两项完成并勾选**（PR #20）：IeltsDirector 导演状态机（p1→p2_prep→p2_talk→p2_followup→p3→done）+ 方括号导演提示 + 中立考官 persona + P2 备题子状态（60s 输入暂停/ready 提前）。三个实锤修复：音频门控计轮（空回执轮防抢跑）、计时器防自取消（CancelledError 截断指令帧致 1007/1008 的根因）、system_instruction Content 形状。pytest 175 绿 + review NEEDS-FIX(C1/W1)→修→复审 PASS；真 Live 验证至长谈邀请，长谈中段偶发 1008 记 P8 复查。前端浮层（cue card/倒计时/笔记/ready）契约见 handoff/inbox/005。下次：P5 情景 persona 或等联调
2026-06-07 — **P4 后端五项全部完成**（PR #16/#17/#18/#19，#15 已先行）：数据模型升级（settings/is_seed/status 枚举+user_version 门控迁移）→ 会话化接口（POST /sessions 族，竞态关死/重录去重）→ judge 按 sub_mode（方式 B 无数字 band、可评性只看诊断层）→ TTS 预生成（24/24 真跑全生成）。pytest 163 绿；四轮独立 review（两轮 NEEDS-FIX 阻断项均修复后复审 PASS）；三次真冒烟（方式 B 双题 38s 报告/B 无 band 12s/TTS 回填 200）。判断记录：gemini-2.5-flash 间歇 503 风暴，B 冒烟改 JUDGE_MODEL=flash-lite 绕行验证（生产默认不动）。**BREAKING 汇总待 handoff/inbox/004**：status 枚举改名、POST /recordings→/sessions 族、B 报告无 band。下次：投递 handoff 004 → P3 导演状态机（live 巷道已清）
2026-06-07 — P4 第 4 项题库完成并勾选（PR #15，连带勾 P3 第 3 项 cue card 库）：data/questions.json p1×8/p2×8 cue cards/p3×8 + GET /questions?part=（中文 422、id 内容 pin）+ /static/tts 挂载（tts_url 按文件存在性逐请求回填，TTS 落地免重启）；pytest 130 绿 + review NEEDS-FIX(C1 挂载缺失+W1-W5)→全修。与并行会话 PR #14 同窗零冲突（巷道隔离）。下次：P4b 数据模型升级（settings 表+is_seed+status 枚举）→ P4c 会话化接口 → P4d judge 按 sub_mode → P4e TTS 预生成；方式 B 后端齐后一次性 handoff 前端
2026-06-07 — P2 第 5、7 项完成并勾选（**P2 全部完成**）：PTT（turn=ptt 关内建 VAD + 上行首帧 activity_start + turn_end→activity_end，natural 误发 turn_end 忽略不断流）+ 延迟徽章（LatencyMeter 相位机：ptt 以 turn_end 为停说点、natural 以最后非静音帧近似，考官首帧发 latency_ms 一轮一次）；pytest 130 绿（+16 用例，假时钟确定性）+ 真冒烟（ptt VAD 关实锤·latency 894ms / natural 2299ms）+ review PASS（warning/建议已修）/ judge 上游 503 持续未恢复（与本变更无关）/ 下次从 P3 导演状态机或 P4 方式 B 开始
2026-06-07 — **P5 后端两项完成并勾选**（PR #21）：`app/scenario_cases.py` case 注册表（ordering/meeting persona + judge 侧重段；/ws/live 白名单由注册表推导、finalize 回填 case_prompt、未知 case 降级占位不 failed；persona 内置方括号指令规则为拓展项 ask_help 预留接线）。pytest 183 绿（+8）+ 三轮真冒烟（judge 无 band 命中点餐侧重·planted "want eat" 捕获 / ordering·meeting persona 真 Live 守角色 + 自然收尾）+ review PASS。ask_help 破壁按用户决策移入拓展区（不在 24h 主线）；handoff/inbox/006 情景前端接入契约已投递。下次：P6 后端件 PR-A（GET /sessions + GET /progress + settings API）
2026-06-07 — **P6 后端件 PR-A 完成**（PR #22，P6 两项标 [~] 余前端）：GET /sessions（Library 倒序 + overall_band/wpm 摘要分 LEFT JOIN + status/is_seed，契约加 status）+ GET /progress（band_series 仅方式 A 三重过滤 / fluency_series 全模式含 error_rate / latest_bands / gap=target−latest 正负语义）+ GET/PUT /settings（0–9 且 0.5 倍数，null 清除）；SCHEMA §6.2/§6.4 字段名锁定。pytest 201 绿（+18）+ 真冒烟（真 oral.db：51 行列表 / 11 band 点 + 18 流利度点 / gap 计算正确 / 422 生效）+ review PASS（2🟡 测试缺口已补）。handoff/inbox/007 F5 契约件已投递（注明 seed 脚本未做、真库暂无 is_seed 行）/ 无阻塞 / 下次：P6 seed 脚本或修方式 A done 不发（done/005 🔴 模型抢戏）
2026-06-07 — **P6 seed 脚本完成并勾选**（PR #23）：`python -m app.seed` 7 条历史会话（A×3 band 5.5→6.0→6.5 真聚合 + B×2 + 情景×2；wpm/静默/填充/错误率/ttr 单调向好）；幂等重插 + --purge 只删 seed 行（真实行零波及测试钉死）；report_json 经 Report 模型同 schema、evidence 纯英文 ASR 转写体 + CJK 护栏。pytest 212 绿（+11）+ 真冒烟（seed→曲线爬升→purge 还原）+ review 首轮 NEEDS-FIX（🔴 evidence 引证违规×5）→修→复审 PASS。F5 前端随 007 回执 PASS 收官（Library+Review 两页真数据联调过，error_rate 加线已采纳）；007 反馈记两条新 TODO（live duration_s 漏落库 / 瞬态残留清理）；真库已播种 + handoff/inbox/008 验证件已投。下次：修 live duration_s 或方式 A done 不发（done/005 🔴）
2026-06-07 — **live duration_s 回填完成并勾选**（PR #24，done/007 反馈①闭环）：session_started 后记单调钟起点，end_session 回调内墙钟差值回填 + 翻 processing 同瞬间；弃局不回填留 NULL；方式 B 互踩不可能（status 门 409）。pytest 213 绿（+1 用例 + 弃局 NULL 不变式断言）+ 真冒烟（真 Live 建链 sleep 2.2s→库里 2.20s 精确吻合）+ review PASS。存量旧 live 行仍 '—' 属预期（不回写历史）。下次：修方式 A done 不发（done/005 🔴 模型抢戏）或 P8 残留清理
2026-06-07 — **P0–P6 后端全量巡检**（7 子 agent 并行，一人一 Priority，只读审计）：去重后产出 3🔴 + 12🟡 + 4🔵 打包项，新开 P9 巡检修复批次记录（每条带文件:行号与来源）。🔴：pyaudio 主依赖破坏 uv sync / 方式 A done 不发零修复 / _pick_cue_card 空库 IndexError。亮点确认干净：竞态关死、band 剥除三重防线、迁移原子性、注册表白名单、零 TODO/FIXME 残留。未动任何代码 / 无阻塞 / 下次：从 P9 🔴 三项开工（pyaudio 最小、done 不发价值最大）


