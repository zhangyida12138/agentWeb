from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

class ProcessTimeMiddleware(BaseHTTPMiddleware):
    """写入 X-Process-Time header（毫秒，保留 2 位小数）。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        elapsed_ms = (perf_counter() - start) * 1000.0
        response.headers["X-Process-Time"] = f"{elapsed_ms:.2f}"
        return response
