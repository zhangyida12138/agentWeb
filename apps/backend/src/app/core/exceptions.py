import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.application.exceptions import (
    ApplicationError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
)
from app.domain.exceptions import DomainError

logger = logging.getLogger(__name__)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


async def _handle_not_found(_request: Request, exc: Exception) -> JSONResponse:
    return _error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))


async def _handle_conflict(_request: Request, exc: Exception) -> JSONResponse:
    return _error_response(status.HTTP_409_CONFLICT, "conflict", str(exc))


async def _handle_domain_error(_request: Request, exc: Exception) -> JSONResponse:
    """领域规则被违反，通常是入参不满足业务约束。"""
    return _error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, "domain_error", str(exc))


async def _handle_application_error(_request: Request, exc: Exception) -> JSONResponse:
    return _error_response(status.HTTP_400_BAD_REQUEST, "application_error", str(exc))


def register_exception_handlers(app: FastAPI) -> None:
    """把分层异常统一映射为 API 错误响应。"""
    app.add_exception_handler(EntityNotFoundError, _handle_not_found)
    app.add_exception_handler(EntityAlreadyExistsError, _handle_conflict)
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(ApplicationError, _handle_application_error)
