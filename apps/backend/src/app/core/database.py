from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# 全局唯一的 async engine（进程级别，勿频繁创建销毁）
engine = create_async_engine(
    settings.db.url,
    echo=settings.db.echo,
    pool_size=settings.db.pool_size,
    max_overflow=settings.db.max_overflow,
    pool_pre_ping=settings.db.pool_pre_ping,
    future=True,
)

# 会话工厂：expire_on_commit=False 保证 commit 后实体仍可读取
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入入口——唯一的事务边界。

    任何仓储 / 用例层都不允许自行 commit / rollback / close。
    """

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise  # 保持异常传播，不能删除
        finally:
            await session.close()  # 上下文管理器本身就会close，这里是冗余
