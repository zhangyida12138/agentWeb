import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings

# 导入全部模型后 Base.metadata 才包含所有表定义（autogenerate 依赖它）
from app.infrastructure.persistence import models  # noqa: F401
from app.infrastructure.persistence.base import Base

config = context.config

# 以编程方式调用 alembic（例如测试夹具）时，可以通过 config.attributes
# 里的 skip_logging_config 让我们跳过 [logger_*] 段：
# fileConfig() 默认 disable_existing_loggers=True，会把 pytest 与业务已经装好的
# logger 全部关掉——测试失败时最需要的日志反而最先消失。
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    fileConfig(config.config_file_name)

_settings = get_settings()
# 数据库地址统一由应用配置提供，只需维护 DB__URL / .env
# 这里直接沿用 asyncpg 的异步 URL：在线迁移本来就是 async_engine_from_config，
# 离线模式（只渲染 SQL）也不需要真连库，没必要为此多引一个同步驱动依赖。
config.set_main_option("sqlalchemy.url", _settings.db.url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不建立数据库连接。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
