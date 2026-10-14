"""pytest 全局夹具。

测试策略：**真实 PostgreSQL（独立测试库）+ 每个用例一个最终回滚的事务**。

为什么不 mock 数据库：
    本项目最容易出事的地方恰恰是「ORM 映射 / 唯一索引 / 事务提交时机」这类
    只有真库才会暴露的问题（例如唯一约束冲突在 flush 还是 commit 才抛）。
    mock 掉之后测试全绿、上线就炸，等于白写。

隔离性靠两层保证：
    1. **库级**：测试连的是 docker-compose 里的 ``postgres-test`` 容器
       （5433 / agent_web_test，独立实例、独立数据卷），碰不到开发数据。
       相关变量都在 ``apps/backend/.env.test``，本文件把 APP__ENV 钉成 test 后自动加载。
    2. **用例级**：每个用例开一个外层事务，被测代码的 ``session.commit()`` 只释放 SAVEPOINT
       （``join_transaction_mode="create_savepoint"``），用例结束时外层事务整体回滚。
       于是用例之间互不污染，也不需要清库或按顺序执行。

测试库不需要手动准备：
    会话级夹具 ``prepared_test_database`` 会「防呆 → 等库可连 → 迁移到 head」。
    故意不写成「先手动跑两条命令」——那种前置步骤一定会被忘记，
    而忘记的后果不是报错，是连上开发库还一切正常。
    它是 ``db_engine`` 的依赖，所以只有会连库的用例（integration）才需要它：
    单跑 ``pytest tests/unit`` 连 Docker 都不必起。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# ⚠️ 必须排在 import app.* 之前，而且必须是**赋值**不是 setdefault。
#    1) config.py 在**模块被导入的那一刻**就要按 APP__ENV 决定加载哪些 env 文件
#       （见那边的 _ENV_FILES），晚一步就定格了；
#    2) 本进程就是测试进程，环境只能是 test。用 setdefault 的话，
#       外部一旦导出过 APP__ENV=development，测试就会去读开发那份 .env、
#       连上开发库——而且因为开发库本来就有表结构，跑起来一切「正常」。
os.environ["APP__ENV"] = "test"

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

# 等测试库就绪：单次连接 2 秒上限 × 最多 12 次 ≈ 30 秒封顶。
# 上限存在的意义是「失败要快、要给出可操作的提示」，而不是无限期地卡住。
# 正常路径不会用到这么多次：make db-test-up 自带 --wait，容器健康后才轮到 pytest。
_CONNECT_TIMEOUT_SECONDS = 2
_REACHABILITY_ATTEMPTS = 12


def _assert_is_test_database(url: str) -> None:
    """拦住「测试连上开发库」——本文件里最便宜、也最值钱的一道检查。

    连错库的典型症状不是报错，而是「测试全绿 + 开发数据被悄悄改掉」：
    开发库本来就有表结构，迁移变成空操作，全部用例照样跑得过去。
    规则取最笨、也最不容易被绕过的那个：**库名必须以 ``_test`` 结尾**。
    """

    name = make_url(url).database or ""
    if not name.endswith("_test"):
        msg = (
            f"拒绝在数据库 {name!r} 上跑测试：库名必须以 _test 结尾。\n"
            f"当前 DB__URL = {url}\n"
            "请检查 apps/backend/.env.test，"
            "以及是否有外部环境变量（DB__URL / APP__ENV）覆盖了它。"
        )
        raise RuntimeError(msg)


async def _wait_until_reachable(url: str) -> None:
    """等测试库能连上（最多约 30 秒）。

    容器刚 ``up`` 完时 Postgres 还在初始化，第一次连接会 ConnectionRefused；
    与其让第一次跑测试的人撞上这个竞态，不如在这里重试几秒——起的只是本机容器。

    ``connect_args={"timeout": 2}`` 是本函数的重点：Docker Desktop 在容器停掉后
    宿主机端口未必立刻拒连（docker-proxy 可能先把 SYN 接下来再晾着），
    不设上限的话单次 ``connect()`` 会一直等到 asyncpg 的 60 秒默认超时——
    库没起来时人只会看到「卡住」，而不是看到我们要给他的那句提示。
    """
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"timeout": _CONNECT_TIMEOUT_SECONDS}
    )
    try:
        for _ in range(_REACHABILITY_ATTEMPTS):
            try:
                async with engine.connect():
                    return
            except Exception:
                # 只区分「还没起来」和「起来了」，所以这里宽泛捕获：
                # 连接失败可能是 OSError / TimeoutError / asyncpg 的各种子类，
                # 逐个枚举只会漏。最后一次不再吞异常，把真正的原因
                # （端口 / 密码 / 库名）原样抛出来。
                await asyncio.sleep(0.5)
        async with engine.connect():
            return
    finally:
        await engine.dispose()


def _upgrade_schema_to_head() -> None:
    """把测试库的表结构推到最新迁移版本。

    用 Alembic 而不是 ``Base.metadata.create_all()``：测试库的 schema 应当和生产
    走同一套 DDL，否则「模型改了但忘了写迁移」这类问题在测试里永远看不见。

    幂等：已经在 head 时只多读一次版本表，重复跑几乎不花时间。
    故意**不** DROP DATABASE 重建——独立容器 + 用例级回滚已经保证了清洁，
    每次重建只是白白多出「还有别的连接占用」这种失败模式。
    """

    config = AlembicConfig(str(_ALEMBIC_INI))
    # 让 env.py 跳过 [logger_*] 段：fileConfig() 默认 disable_existing_loggers=True
    # 且把 root 降到 WARNING，会把 pytest 期间的业务日志整个吞掉
    # （排查测试失败时最需要它们）。走 attributes 而不是清空 config_file_name——
    # 后者会让 alembic 连 ini 本身都不解析（file_config 是 memoized property，
    # 首次访问时看到文件名已空就只造一个空配置，连 script_location 都会丢）。
    config.attributes["skip_logging_config"] = True
    # ini 里写的是相对路径（`. src`），alembic 按 cwd 解析；这里换成绝对路径与 cwd 解耦
    config.set_main_option(
        "prepend_sys_path",
        os.pathsep.join([str(_BACKEND_DIR), str(_BACKEND_DIR / "src")]),
    )
    alembic_command.upgrade(config, "head")


@pytest.fixture(scope="session")
def prepared_test_database() -> Iterator[None]:
    """会话级准备：防呆 → 等库可连 → 迁移到 head。

    **刻意不加 autouse**：上面的依赖链是 client → db_session → db_engine →
    本夹具，所以只有真正会连库的用例才需要它。单跑 ``pytest tests/unit``
    时没有任何用例请求它，连 Docker 都不必起（单元测试用内存仓储）。

    为什么是**同步**夹具：pytest-asyncio 是 function 级事件循环，会话级异步夹具要跨
    多个 loop，会被直接拒绝；而 alembic 的 env.py 内部自己调 ``asyncio.run()``，
    只有在「没有正在运行的 loop」的同步上下文里才安全。
    这个夹具也因此不会和 pytest-asyncio 的 loop 打架。
    """

    url = get_settings().db.url
    _assert_is_test_database(url)
    try:
        asyncio.run(_wait_until_reachable(url))
    except Exception as exc:
        msg = (
            f"连不上测试数据库：{url}\n"
            "先启动它：make db-test-up（等价于 docker compose up -d postgres-test）"
        )
        raise RuntimeError(msg) from exc
    _upgrade_schema_to_head()
    yield


@pytest.fixture
async def db_engine(prepared_test_database: None) -> AsyncIterator[AsyncEngine]:
    """每个用例独立建引擎，用完即销毁。

    多一个形参 ``prepared_test_database`` 不是为了用它，而是为了声明依赖：
    有它挡在前面，引擎建立时测试库已经确认可连、且 schema 已迁到 head。

    连的是 ``.env.test`` 里的测试库。

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
