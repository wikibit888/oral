"""应用配置：集中从环境变量 / .env 读取，全局单例 `settings`。

密钥只放 .env（已被 .gitignore 忽略），禁止写进代码或提交。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini（Live / judge 复用）
    gemini_api_key: str = ""
    gemini_proxy: str | None = None

    # judge 用的多模态模型（结构化输出 + 听音频判发音）
    judge_model: str = "gemini-2.5-flash"

    # judge 思考预算（token）：0=关闭思考（默认，省课后首字延迟）  -1=自动  正值=固定档。
    # 2.5-flash 允许 0；temp=0 grounded judge 关思考不引漂移。留开关便于 A/B 与一键回滚。
    judge_thinking_budget: int = 0

    # judge 请求超时（毫秒）：上游挂起不回包时，超时抛错→重试→最终 failed，
    # 不让 to_thread 线程永久阻塞、会话永久卡 processing（故障定位 #3）。
    # 30s：flash 关思考的单次推理只需数秒，30s 已是"明显异常"阈值；同时让最坏
    # 重试总时长（≈5×30s）仍小于前端 stalled 判据 MAX_PROCESSING_MS=180s，避免误判。
    # 该超时也作用于 Files API 切片上传（秒级小文件，30s 充裕；超时仅降级 inline）。
    judge_timeout_ms: int = 30000

    # judge 结构化输出 token 上限：0 / 负值 = 不设（用模型默认上限，避免反而缩小留白
    # 造成截断）；正值 = 显式上限（调优用）。截断由 finish_reason=MAX_TOKENS 检测兜底。
    judge_max_output_tokens: int = 0

    # 实时对话用的 Live 模型（WS 双向音频流：16k PCM 上行 / 24k PCM 下行）
    live_model: str = "gemini-3.1-flash-live-preview"

    # Live 音色。空字符串（默认）= 方式 A 每场从 director.EXAMINER_VOICES 注册表
    # 随机抽一个（考官自报姓名与音色一一对应、同源派生）；填音色名（如 LIVE_VOICE=
    # Aoede）则固定用它——注意 pin 对两模式都生效（情景路径也固定为该音色）。
    # 情景对话不参与随机：空 = 模型默认音色（Puck），不变。
    live_voice: str = ""

    # 题库 TTS 预生成模型（python -m app.tts，离线一次性）
    tts_model: str = "gemini-2.5-flash-preview-tts"

    # SQLite 数据库文件路径（单写死 demo 用户的本地存储）
    db_path: str = "oral.db"

    # 录音 / 切片落盘目录
    audio_dir: str = "data/audio"

    # faster-whisper 转写（模型首次调用自动下载权重）
    whisper_model: str = "small"          # tiny | base | small | medium | large-v3
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str = "en"          # 空字符串 = 自动检测

    # 服务监听地址
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 热重载（默认开）。联调 live 会话时置 APP_RELOAD=0：reload 重启进程会
    # 掐断所有进行中的 WS 会话（联调发现②）
    app_reload: bool = True

    # 允许跨域的前端来源（React dev server：Vite 5173 / CRA 3000）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


settings = Settings()
