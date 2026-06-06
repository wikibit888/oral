"""FastAPI 应用工厂：装配中间件与路由，导出 `app` 供 uvicorn 加载。

已挂载课后录音—评流水线（POST /recordings、GET /reports/{id}）
与实时对话 WS 代理（/ws/live）。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.live_ws import router as live_ws_router
from app.api.questions import TTS_DIR, TTS_URL_PREFIX, router as questions_router
from app.api.recordings import router as recordings_router
from app.api.reports import router as reports_router
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时按 schema.sql 建表（幂等）
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI 英语口语陪练",
        description="单人 24h 可交付的本地 demo —— 课后评测引擎 + 实时对话。",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(recordings_router)
    app.include_router(reports_router)
    app.include_router(live_ws_router)
    app.include_router(questions_router)

    # 预生成 TTS 音频静态挂载（SCHEMA §6.5）。目录启动即建：tts_url 引用的
    # 路由必须真实存在，否则文件落地后 URL 指向 404（review C1）。
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(TTS_URL_PREFIX, StaticFiles(directory=str(TTS_DIR)), name="tts")

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"app": "oral", "docs": "/docs"}

    return app


app = create_app()
