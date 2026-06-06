-- AI 英语口语陪练 —— SQLite 表结构（对齐 PRD §8.1）
-- 单写死 demo 用户：不设 users 表、无账号 / 多用户。
-- 关键列正规化，完整报告以 JSON blob 原样存（reports.report_json）。

-- 一次练习会话：雅思方式 A/B 或情景对话
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,                              -- uuid
    mode          TEXT NOT NULL CHECK (mode IN ('ielts', 'scenario')),
    sub_mode      TEXT,                                          -- 雅思: exam | module_p1 | module_p2 | module_p3
    scenario_case TEXT,                                          -- 情景: ordering | meeting
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    duration_s    REAL,
    audio_path    TEXT,                                          -- 整段会话音频
    -- 状态枚举（SCHEMA §5.1）: live(Live 会话中) | recording(方式 B 录音中)
    --   | processing(judge 跑中) | completed(报告就绪) | failed
    -- 不设 DEFAULT：调用方必须显式给状态，杜绝静默落错态（review S1）
    status        TEXT NOT NULL,
    is_seed       INTEGER NOT NULL DEFAULT 0                     -- Library 标注"演示数据"
);

CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions (started_at);

-- 单 demo 用户设置（单行表，id 恒为 1）：Review 面板目标差距用
CREATE TABLE IF NOT EXISTS settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    target_band REAL                                             -- 用户目标 band；未设置为 NULL
);

INSERT OR IGNORE INTO settings (id, target_band) VALUES (1, NULL);

-- 每个对话回合（用户 / 考官 / persona），含课后切片用的时间戳与音频片段。
-- 增量流水线（SCHEMA §3）：切片落地即后台转写 + Files API 预上传，结果挂本行；
-- 会话结束 finalize 只剩一次 judge 调用。
CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                               -- user | examiner | persona
    text            TEXT,                                        -- 转写文本
    start_ts        REAL,                                        -- 相对会话起点的秒数（单调时钟）
    end_ts          REAL,
    clip_path       TEXT,                                        -- 该回合用户音频切片
    transcript_json TEXT,                                        -- 切片级词时间戳转写（增量产物）
    file_uri        TEXT                                         -- Files API 预上传 URI（judge 引用）
);

CREATE INDEX IF NOT EXISTS idx_turns_session_id ON turns (session_id);

-- 课后报告：一会话一份。雅思四维 band（情景为 NULL）；通用流利度指标用于跨会话曲线；
-- 完整报告 schema（PRD §6.2）原样存 report_json。
CREATE TABLE IF NOT EXISTS reports (
    session_id    TEXT PRIMARY KEY REFERENCES sessions (id) ON DELETE CASCADE,
    mode          TEXT NOT NULL,
    overall_band  REAL,                                          -- 仅雅思；情景为 NULL
    fc_band       REAL,                                          -- Fluency & Coherence
    lr_band       REAL,                                          -- Lexical Resource
    gra_band      REAL,                                          -- Grammatical Range & Accuracy
    pron_band     REAL,                                          -- Pronunciation
    wpm           REAL,                                          -- 通用流利度指标（跨会话追踪）
    silence_ratio REAL,
    filler_pm     REAL,                                          -- 填充词每分钟密度
    ttr           REAL,                                          -- type-token ratio（Vocabulary Diversity）
    error_rate    REAL,
    report_json   TEXT NOT NULL,                                 -- 完整报告 JSON
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
