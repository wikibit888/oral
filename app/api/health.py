"""健康检查端点：确认服务存活，供前端联调与部署探活。"""

from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
