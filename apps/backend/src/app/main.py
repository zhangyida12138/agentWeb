from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from loguru import logger

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers, success_response
from app.core.logging import setup_logging
from app.core.middleware import MIDDLEWARES
from app.presentation.api.v1.router import api_router

settings = get_settings()


async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：启动初始化 → yield 处理请求 → 关闭清理。"""

    setup_logging(debug=settings.app.debug)
    logger.info(
        "🚀 App starting: name={name} env={env} debug={debug}",
        name=settings.app.name,
        env=settings.app.env,
        debug=settings.app.debug,
    )
    yield  # 所有请求都在 yield 与 finally 之间处理
    logger.info("🛑 App shutdown complete")


# 实例化 FastAPI（docs_url 仅在允许时开启）
app = FastAPI(
    title=settings.app.name,
    debug=settings.app.debug,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app.docs_enabled else None,
    redoc_url="/redoc" if settings.app.docs_enabled else None,
    openapi_url="/openapi.json" if settings.app.docs_enabled else None,
)

# ⚠️ 注册顺序严格遵守：异常 → 中间件 → 路由（洋葱层从外到内依次构建）
register_exception_handlers(app)

for mw in MIDDLEWARES:
    app.add_middleware(mw.cls, *mw.args, **mw.kwargs)

app.include_router(api_router)


# 根路径：开发跳 docs，生产报个信
@app.get("/", include_in_schema=False, response_model=None)
async def root() -> RedirectResponse | dict:
    if settings.app.docs_enabled:
        return RedirectResponse(url="/docs")
    return success_response(
        {"name": settings.app.name, "env": settings.app.env},
        message="AgentWeb API is running",
    )
