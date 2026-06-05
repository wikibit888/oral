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

    # Gemini（Live / judge 后续复用；骨架阶段仅加载，暂不使用）
    gemini_api_key: str = ""
    gemini_proxy: str | None = None

    # SQLite 数据库文件路径（单写死 demo 用户的本地存储）
    db_path: str = "oral.db"

    # 录音 / 切片落盘目录
    audio_dir: str = "data/audio"

    # 服务监听地址
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 允许跨域的前端来源（React dev server：Vite 5173 / CRA 3000）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


settings = Settings()
