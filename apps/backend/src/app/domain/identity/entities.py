"""身份上下文的实体（聚合根）。

铁律：本层不 import 任何框架；密码明文 → 哈希的过程属于 shared 工具，
实体只接收已经哈希好的字符串，绝不接触明文。

顺带记一笔下面这行 ``from __future__ import annotations`` 的作用：
在定义类的内部，可以直接使用这个类作为类型注解。

    class Node:
        def next_node(self) -> Node:  # ❌ 报错！解析 Node 这一行时，Node 类还没定义完成
            ...

    class Node:
        def next_node(self) -> "Node":  # 字符串形式的前向引用
            ...

    from __future__ import annotations

    class Node:
        def next_node(self) -> Node:  # ✅ 直接写类名，不会报错
            ...

注意这段笔记只能待在 docstring 里：``from __future__`` 必须是文件里的第一条
语句，夹在它前面的任何表达式（哪怕只是一个字符串字面量）都会让整个模块
SyntaxError——不是 lint 警告，是连 import 都进不去。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.domain.identity.exceptions import InactiveUserError, WeakPasswordError
from app.domain.identity.value_objects import Email, Username

# bcrypt 哈希固定 60 字符，这里给一个宽松下限做「误传明文」的兜底
_MIN_HASH_LEN = 20

# 用于区分「未传该字段」与「显式置空」
_UNSET: Any = object()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _assert_hashed(password_hash: str) -> None:
    """确认拿到的是哈希而不是明文（bcrypt 哈希固定 60 字符，这里只兜下限）。"""
    if not password_hash or len(password_hash) < _MIN_HASH_LEN:
        raise WeakPasswordError("密码哈希不合法")


def _blank_to_none(value: Any) -> Any:
    """把空串按「清空」处理。

    空串在业务上不表达任何信息：存进去只会得到「有值但看不见」的字段，
    前端渲染出空白、判空逻辑还得写两套（``if bio`` 与 ``if bio is None``）。
    统一在实体这一层收敛，比让每个调用方各自记得 strip 更可靠。
    注意只认「纯空串」，不顺手 strip：``"  "`` 是客户端自己的输入，不该被悄悄改写。
    """
    return None if value == "" else value


@dataclass(slots=True)
class User:
    """用户聚合根：承载身份相关的业务不变量。"""

    email: Email
    username: Username
    password_hash: str
    id: UUID | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    @classmethod
    def register(
        cls,
        *,
        email: Email,
        username: Username,
        password_hash: str,
        display_name: str | None = None,
    ) -> User:
        """注册工厂：生成标识，让「新用户」只有一个构造入口。

        标识为什么由领域生成：``users.id`` 是主键，持久化层要求实体进入仓储时
        已经带着标识（见 mappers.to_model 的断言），否则无法区分「内存里刚 new
        出来的实体」与「从库里读出来的实体」——主键缺失时两者语义上无从辨认。
        """
        _assert_hashed(password_hash)
        return cls(
            email=email,
            username=username,
            password_hash=password_hash,
            id=uuid4(),
            display_name=display_name,
        )

    def change_password(self, new_password_hash: str) -> None:
        """更换密码。

        ⚠️ 入参必须是**哈希后**的字符串（明文 → 哈希由 shared.security 完成），
        这里只做长度兜底，防止把明文误写进 password_hash。
        """
        _assert_hashed(new_password_hash)
        self.password_hash = new_password_hash
        self._touch()

    def update_profile(
        self,
        *,
        display_name: Any = _UNSET,
        avatar_url: Any = _UNSET,
        bio: Any = _UNSET,
    ) -> None:
        """局部更新资料：显式传 None（或空串）表示清空该字段。"""
        if display_name is not _UNSET:
            self.display_name = _blank_to_none(display_name)
        if avatar_url is not _UNSET:
            self.avatar_url = _blank_to_none(avatar_url)
        if bio is not _UNSET:
            self.bio = _blank_to_none(bio)
        self._touch()

    def deactivate(self) -> None:
        """停用账号（软封禁，数据保留）。"""
        self.is_active = False
        self._touch()

    def activate(self) -> None:
        """恢复账号。"""
        self.is_active = True
        self._touch()

    def ensure_active(self) -> None:
        """账号可用则放行，否则抛领域异常（登录与后续鉴权共用这道守卫）。"""
        if not self.is_active:
            raise InactiveUserError()

    def _touch(self) -> None:
        self.updated_at = _utc_now()


__all__ = ["User"]
