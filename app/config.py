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

    # 允许跨域的前端来源（React dev server：Vite 5173 / CRA 3000）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


settings = Settings()
