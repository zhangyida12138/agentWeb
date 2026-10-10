from fastapi import APIRouter

from app.presentation.api.v1.endpoints.health import router as health_router

# v1 总路由：所有业务 endpoint 都在这里 include
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router, tags=["health"])

__all__ = ["api_router"]
