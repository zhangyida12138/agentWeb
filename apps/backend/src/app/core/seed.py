"""启动时的种子数据：把 domain 里声明的角色 / 权限矩阵幂等同步进数据库。

设计要点（对应 PLAN.md 3.5 与 backend.md 的「幂等同步」）：
    ① 事实来源是**代码里的声明**（domain/access/entities.py 的 ROLE_SPECS /
       PERMISSION_SPECS），不是数据库现状；
    ② 可反复执行：重复运行不产生任何新行（对齐逻辑见 SqlAccessRepository）；
    ③ 自己开独立会话并提交 —— lifespan 阶段没有请求上下文，
       用不上 get_db 那个「请求级事务」。

为什么不在这里写业务判断：
    种子只该做「搬运」。任何 if 形式的规则判断都是领域知识，
    应该待在 domain/access/entities.py 的声明里。
"""

from __future__ import annotations

from loguru import logger

from app.core.database import AsyncSessionLocal
from app.domain.access.entities import PERMISSION_SPECS, ROLE_SPECS
from app.infrastructure.persistence.repositories.access import SqlAccessRepository


async def seed_access_catalog() -> dict[str, int]:
    """幂等同步角色与权限，返回本次的写入统计。"""

    async with AsyncSessionLocal() as session:
        repo = SqlAccessRepository(session)
        result = await repo.sync_catalog(ROLE_SPECS, PERMISSION_SPECS)
        await session.commit()
    logger.info("🌱 权限种子数据已对齐: {result}", result=result)
    return result


__all__ = ["seed_access_catalog"]
