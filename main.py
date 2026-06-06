"""开发入口：`uv run python main.py` 启动 FastAPI 服务。

默认带热重载；联调 live 会话时用 `APP_RELOAD=0 uv run python main.py`——
reload 重启进程会掐断所有进行中的 WS 会话。
"""

import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
    )


if __name__ == "__main__":
    main()
