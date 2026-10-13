"""access（角色 / 权限）相关的请求与响应 Schema。

与 ``schemas/auth.py`` 同一套约定：
    请求约束只在这里声明；响应字段只暴露该暴露的——``RoleResponse`` 里没有
    ``permission_ids`` 之类内部主键，前端拿到的是可读的 ``permission_codes``。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.presentation.api.v1.schemas.auth import (
    PASSWORD_MAX_LEN,
    PASSWORD_MIN_LEN,
    UserResponse,
)

# 与 domain/access/entities.py 的 ROLE_CODE_MAX_LEN 保持一致。
# 同样地，两处都写一遍是有意的：schema 负责「尽早给出 422 友好提示」，
# 领域常量负责「无论从哪个入口进来都合法」，后者才是安全边界。
ROLE_CODE_MAX_LEN = 50
# 单个用户最多挂几个角色。本来只有 3 个内置角色，这个上限是给
# 「恶意构造 10 万个角色码让服务端逐个查库」这类输入兜底的
MAX_ROLES_PER_USER = 20


# 角色码的字段级约束：strip_whitespace 让 " reader " 也能正确识别，
# 免得前端拼接字符串时多带一个空格就变成「角色不存在」
RoleCodeField = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=ROLE_CODE_MAX_LEN,
    ),
]


# ──────────────────────────── 请求 ────────────────────────────


class AssignRolesRequest(BaseModel):
    """分配角色入参（**替换**语义）。

    ``role_codes`` 是最终状态而不是增量：
        前端交互就是「勾选若干个 → 保存」，一次请求表达完整结果，
        天然幂等——重复提交不会叠加，也不会漏删。
    用 ``set`` 而不是 ``list``：同一个角色写两遍是脏输入，
    在 schema 层直接去重比在用例里再防一次更早、更干净。
    """

    role_codes: set[RoleCodeField] = Field(
        default_factory=set,
        max_length=MAX_ROLES_PER_USER,
        description="该用户最终应拥有的角色编码集合；传空集合表示收回全部角色",
    )


class ResetPasswordRequest(BaseModel):
    """管理员重置密码入参。

    只有 ``new_password``，**没有** ``old_password``——这不是省字段，是接口语义：
        管理员不知道、也不该知道目标用户的旧密码。强行要求它，
        等于把「用户忘记密码」这个唯一的求助场景堵死。
    因此这个字段的替代担保不是旧密码，而是 ``user:reset_password`` 权限。

    密码长度复用 ``schemas/auth.py`` 的常量，不在 access 里另立一份：
        同一套密码策略出现在两个模块，早晚会改一处漏一处。
    """

    new_password: str = Field(
        min_length=PASSWORD_MIN_LEN,
        max_length=PASSWORD_MAX_LEN,
        description=f"新密码，长度 {PASSWORD_MIN_LEN}-{PASSWORD_MAX_LEN}",
    )


# ──────────────────────────── 响应 ────────────────────────────


class PermissionResponse(BaseModel):
    """权限点出参。"""

    # 让它能直接从应用层 DTO（dataclass）构造
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None


class RoleResponse(BaseModel):
    """角色出参：带上它拥有的权限码，前端据 ``permission_codes`` 渲染勾选态。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    permission_codes: set[str] = Field(default_factory=set)


class UserWithRolesResponse(BaseModel):
    """用户列表项：用户视图 + 角色码。

    ``user`` 复用 ``UserResponse`` 而不是另立一套字段：
        用户长什么样，登录接口和管理接口必须给出一致的答案，
        否则前端得为「同一个人」维护两种解析逻辑。
    """

    model_config = ConfigDict(from_attributes=True)

    user: UserResponse
    role_codes: set[str] = Field(default_factory=set)


class UserPageResponse(BaseModel):
    """用户分页出参。"""

    items: list[UserWithRolesResponse]
    total: int = Field(description="总条数（不只是本页），前端据它算总页数")
    offset: int = Field(description="本页起点，已被服务端收敛到合法区间")
    limit: int = Field(description="本页最大条数，已被服务端收敛到合法区间")


class AccessSummaryResponse(BaseModel):
    """当前登录用户的角色码与权限码并集。

    前端把它当成「本次会话能不能看到管理入口」的唯一依据：
        页面上的按钮显不显示，必须和后端守卫用同一个判断，
        否则就会出现「按钮给了、一点就 403」的错位。
    """

    model_config = ConfigDict(from_attributes=True)

    role_codes: set[str] = Field(default_factory=set)
    permission_codes: set[str] = Field(default_factory=set)


__all__ = [
    "MAX_ROLES_PER_USER",
    "ROLE_CODE_MAX_LEN",
    "AccessSummaryResponse",
    "AssignRolesRequest",
    "PermissionResponse",
    "ResetPasswordRequest",
    "RoleCodeField",
    "RoleResponse",
    "UserPageResponse",
    "UserWithRolesResponse",
]
