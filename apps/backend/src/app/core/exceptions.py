from __future__ import annotations

import traceback
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings

# ──────────────────────────── 异常继承链 ────────────────────────────

class DomainError(Exception):
    """领域层 / 全局异常基类。所有业务异常必须继承它。"""

    def __init__(
        self,
        code: int,
        message: str,
        data: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        # 允许显式指定 HTTP 状态；否则从 code 的前 3 位推导（40900 → 409）
        self.http_status = http_status or (code // 100 if 10000 <= code < 60000 else 500)

class ApplicationError(DomainError):
    """应用层（用例编排）异常。"""

class InfrastructureError(DomainError):
    """基础设施层（DB/网络/第三方）异常。"""

# ──────────────────────────── 常用业务异常 ────────────────────────────

class ValidationError(ApplicationError):
    def __init__(self, message: str = "参数校验失败", data: dict | None = None) -> None:
        super().__init__(40000, message, data, status.HTTP_400_BAD_REQUEST)

class AuthenticationError(ApplicationError):
    def __init__(self, message: str = "身份认证失败", data: dict | None = None) -> None:
        super().__init__(40101, message, data, status.HTTP_401_UNAUTHORIZED)

class UnauthorizedError(ApplicationError):
    def __init__(self, message: str = "未登录或 token 过期", data: dict | None = None) -> None:
        super().__init__(40100, message, data, status.HTTP_401_UNAUTHORIZED)

class ForbiddenError(ApplicationError):
    def __init__(self, message: str = "无权限执行该操作", data: dict | None = None) -> None:
        super().__init__(40300, message, data, status.HTTP_403_FORBIDDEN)

class NotFoundError(ApplicationError):
    def __init__(self, message: str = "资源不存在", data: dict | None = None) -> None:
        super().__init__(40400, message, data, status.HTTP_404_NOT_FOUND)

class ConflictError(ApplicationError):
    def __init__(self, message: str = "资源冲突", data: dict | None = None) -> None:
        super().__init__(40900, message, data, status.HTTP_409_CONFLICT)

class InternalServerError(InfrastructureError):
    def __init__(self, message: str = "服务器内部错误", data: dict | None = None) -> None:
        super().__init__(50000, message, data, status.HTTP_500_INTERNAL_SERVER_ERROR)

# ──────────────────────────── 统一响应信封 ────────────────────────────

def success_response(data: Any = None, message: str = "ok", code: int = 0) -> dict[str, Any]:
    """所有成功接口必须通过它构造 body（除非是 SSE/流式）。"""

    return {"code": code, "data": jsonable_encoder(data), "message": message}

# ──────────────────────────── 全局异常处理器 ────────────────────────────

def _mark_handled(request: Request) -> None:
    """在 request.state 上打标记：异常已被全局处理器构造为信封响应。"""

    request.state.is_exception_handled = True


def _json_response(error: DomainError) -> JSONResponse:
    """把 DomainError 转为统一信封的 JSONResponse。"""

    body = {
        "code": error.code,
        "message": error.message,
        "data": jsonable_encoder(error.data),
    }
    resp = JSONResponse(
        status_code=error.http_status,
        content=body,
    )
    # 再加一个 header 级兜底标记，极端情况下（中间件重建 Response）也能识别
    resp.headers["X-Error-Handled"] = "1"
    return resp

def register_exception_handlers(app: FastAPI) -> None:
    """注册全局处理器（在 main.py 路由注册前调用）。"""

    settings = get_settings()

    @app.exception_handler(DomainError)
    async def _domain_handler(request: Request, exc: DomainError) -> JSONResponse:
        _mark_handled(request)
        return _json_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        _mark_handled(request)
        # 把 FastAPI 的 errors 原样塞到 data.errors，前端好提示
        return _json_response(
            ValidationError("请求参数不合法", {"errors": exc.errors()})
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        _mark_handled(request)
        code = exc.status_code * 100  # 404 → 40400，保持 code 位数一致
        msg = exc.detail if isinstance(exc.detail, str) else "请求异常"
        extra = exc.detail if isinstance(exc.detail, dict) else {}
        # 用 ApplicationError 包一层，保持 http_status 推导逻辑一致
        wrapped = ApplicationError(code=code, message=msg, data=extra, http_status=exc.status_code)
        return _json_response(wrapped)

    @app.exception_handler(Exception)
    async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        _mark_handled(request)
        # 兜底：防止任何未捕获异常把 traceback 漏到前端
        err = InternalServerError()
        if settings.app.debug:
            err.data["traceback"] = traceback.format_exc().splitlines()
        return _json_response(err)
