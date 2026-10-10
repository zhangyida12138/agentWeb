from datetime import timezone
from datetime import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import success_response

router = APIRouter()

@router.get("/health", summary="健康检查")
async def health_check(session: AsyncSession = Depends(get_db)) -> dict:
    """验证应用 + 数据库连通性（返回统一信封）。"""

    settings = get_settings()

    # 执行一条最小 SQL 验证 DB 连接（get_db 的事务会在依赖结束时自动提交）
    await session.execute(text("SELECT 1"))

    return success_response(
        {
            "status": "healthy",
            "app": {
                "name": settings.app.name,
                "env": settings.app.env,
                "docs_enabled": settings.app.docs_enabled,
            },
            "db": "ok",
            "timestamp": dt.now(timezone.utc).isoformat(),
        }
    )
