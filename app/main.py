"""FastAPI 应用工厂：装配中间件与路由，导出 `app` 供 uvicorn 加载。

后续 PR 在此挂载录音—评流水线（POST /recordings、GET /reports/{id}）
与实时对话 WS 代理；本 PR 只搭骨架。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.recordings import router as recordings_router
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

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"app": "oral", "docs": "/docs"}

    return app


app = create_app()
