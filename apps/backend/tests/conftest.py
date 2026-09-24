from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.presentation.dependencies import get_user_repository
from tests.fakes import InMemoryUserRepository


@pytest.fixture
def user_repository() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def app(user_repository: InMemoryUserRepository) -> FastAPI:
    """用内存仓储替换真实仓储，接口测试无需连接 PostgreSQL。"""
    application = create_app()
    application.dependency_overrides[get_user_repository] = lambda: user_repository
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
