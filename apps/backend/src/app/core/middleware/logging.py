from time import perf_counter

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import generate_request_id, request_id_var

class LoggingMiddleware(BaseHTTPMiddleware):
    """生成 request_id → 写 ContextVar → 打 access/error 日志 → 写 header。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = generate_request_id()
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        start = perf_counter()

        try:
            response = await call_next(request)
            elapsed_ms = (perf_counter() - start) * 1000.0
            logger.info(
                "{method} {path} → {status} ({elapsed:.2f}ms)",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                elapsed=elapsed_ms,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            elapsed_ms = (perf_counter() - start) * 1000.0
            logger.opt(exception=True).error(
                "{method} {path} !!! {exc_name} ({elapsed:.2f}ms)",
                method=request.method,
                path=request.url.path,
                exc_name=type(exc).__name__,
                elapsed=elapsed_ms,
            )
            raise
        finally:
            request_id_var.reset(token)
