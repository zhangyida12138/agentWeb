"""pytest 全局夹具。

测试策略：**真实 PostgreSQL + 每个用例一个最终回滚的事务**。

为什么不 mock 数据库：
    本项目最容易出事的地方恰恰是「ORM 映射 / 唯一索引 / 事务提交时机」这类
    只有真库才会暴露的问题（例如唯一约束冲突在 flush 还是 commit 才抛）。
    mock 掉之后测试全绿、上线就炸，等于白写。

隔离性怎么保证：
    每个用例开一个外层事务，被测代码的 ``session.commit()`` 只释放 SAVEPOINT
    （``join_transaction_mode="create_savepoint"``），用例结束时外层事务整体回滚。
    于是用例之间互不污染，也不需要清库或按顺序执行。
"""

from __future__ import annotations

import os

# ⚠️ 这两行必须排在 import app.* 之前。
#    get_settings() 是 lru_cache 单例，首次调用之后再改环境变量就不生效了；
#    而 Settings 的优先级是「真实环境变量 > .env > 默认值」，所以这里设的值
#    也会盖住开发用的 .env。
os.environ.setdefault("APP__ENV", "test")
# bcrypt 12 轮单次约 250ms，注册 + 改密会各算两次；4 轮（配置下限）让测试回到毫秒级
os.environ.setdefault("SECURITY__BCRYPT_ROUNDS", "4")

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """每个用例独立建引擎，用完即销毁。

    不用 ``core/database.py`` 里那个全局 engine，也不复用连接池，原因：
        pytest-asyncio 默认是 **function 级事件循环**，每个用例跑在新 loop 上，
        而连接池里缓存的连接还绑着上一个已关闭的 loop——复用时就会
        ``Future attached to a different loop``。NullPool 干脆不缓存，从根上避免。
    """
    engine = create_async_engine(get_settings().db.url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """绑定在「外层事务」上的会话，用例结束后整体回滚。"""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            # 关键：让会话内的 commit 降级为「释放 SAVEPOINT」。
            # 默认行为（rollback_only）下，被测代码一 commit 就把外层事务一起结束了，
            # 回滚无从谈起，数据会真的留在库里。
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """直接对 ASGI 应用发请求的客户端，且把应用的事务边界接到测试会话上。

    ``get_db`` 是整条依赖链（仓储 → 用例 → 端点）的根，所以只覆盖它一处，
    上面所有依赖自动跟着走测试会话——不需要改被测代码一个字符。
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # ASGITransport 不触发 lifespan，用例因此不依赖「启动日志/种子数据」是否就绪
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http
    finally:
        app.dependency_overrides.clear()
