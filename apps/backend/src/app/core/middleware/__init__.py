from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.middleware.logging import LoggingMiddleware
from app.core.middleware.process_time import ProcessTimeMiddleware
from app.core.middleware.response import ResponseWrapperMiddleware

settings = get_settings()

# ⚠️ 注册顺序=洋葱层顺序：最先注册的最外层，先进入、最后退出

# 1. ProcessTime（最外层：全链路计时）

# 2. Logging（次外层：打 request_id，后面所有日志都带）

# 3. CORS（处理预检，放中间避免被后面的中间件改写响应头）

# 4. ResponseWrapper（最内层：包装业务响应）
MIDDLEWARES: list[Middleware] = [
    Middleware(ProcessTimeMiddleware),
    Middleware(LoggingMiddleware),
    Middleware(
        CORSMiddleware,
        allow_origins=[str(o).rstrip("/") for o in settings.cors.allow_origins],
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
        expose_headers=["X-Request-ID", "X-Process-Time"],
    ),
    Middleware(ResponseWrapperMiddleware),
]

__all__ = ["MIDDLEWARES"]
