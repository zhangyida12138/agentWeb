"""集成测试专用夹具。

这里只解决一件事：**把权限种子数据灌进测试事务**。

为什么非要有它：
    ``ASGITransport`` 不触发 lifespan（见根 conftest 的说明），
    所以 ``core/seed.py::seed_access_catalog()`` 在测试里根本不会跑。
    而注册用例现在会给新用户授予默认角色——角色不存在就抛 ``RoleNotFoundError``，
    于是一整批认证用例会以「注册返回 404」的形式挂掉，报错信息还完全指不到这里。

为什么复用 ``db_session`` 而不是直接调 ``seed_access_catalog()``：
    后者自己开 ``AsyncSessionLocal``，写的是**真库**，不受外层事务回滚保护。
    跑一次测试就在开发库里留下三行真实角色数据，下次再跑又同步一遍；
    更糟的是测试之间的隔离性没了——A 用例改过的角色权限，B 用例看得见。
    改用 ``db_session``，种子数据就和用例数据同生共死。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.entities import PERMISSION_SPECS, ROLE_SPECS
from app.infrastructure.persistence.repositories.access import SqlAccessRepository


@pytest.fixture(autouse=True)
async def seeded_access_catalog(db_session: AsyncSession) -> None:
    """把角色 / 权限矩阵同步进本用例的事务里。

    设为 autouse：任何集成用例都可能间接依赖它（哪怕只是调一次注册），
    逐个显式声明只会变成「谁忘了写谁挂」的抽奖。
    同步本身是幂等的（``sync_catalog`` 按编码 upsert），重复调用无害。
    """
    repository = SqlAccessRepository(db_session)
    await repository.sync_catalog(ROLE_SPECS, PERMISSION_SPECS)
