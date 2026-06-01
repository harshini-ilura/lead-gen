import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health_check():
    status: dict = {"db": "ok", "redis": "ok", "status": "healthy"}
    http_status = 200

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        status["db"] = f"error: {exc}"
        status["status"] = "unhealthy"
        http_status = 503

    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as exc:
        status["redis"] = f"error: {exc}"
        status["status"] = "unhealthy"
        http_status = 503

    return JSONResponse(content=status, status_code=http_status)
