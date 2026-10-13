from fastapi import APIRouter

from app.presentation.api.v1.endpoints.auth import router as auth_router
from app.presentation.api.v1.endpoints.health import router as health_router
from app.presentation.api.v1.endpoints.roles import router as roles_router
from app.presentation.api.v1.endpoints.users import router as users_router

# v1 总路由：所有业务 endpoint 都在这里 include
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
# access 上下文：路径前缀已由各自 router 声明（/users、/roles），这里不再加二次前缀
api_router.include_router(users_router)
api_router.include_router(roles_router)

__all__ = ["api_router"]
