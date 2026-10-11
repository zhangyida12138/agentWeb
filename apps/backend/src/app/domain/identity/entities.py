"""身份上下文的实体（聚合根）。

铁律：本层不 import 任何框架；密码明文 → 哈希的过程属于 shared 工具，
实体只接收已经哈希好的字符串，绝不接触明文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.identity.exceptions import WeakPasswordError
from app.domain.identity.value_objects import Email, Username

# bcrypt 哈希固定 60 字符，这里给一个宽松下限做「误传明文」的兜底
_MIN_HASH_LEN = 20

# 用于区分「未传该字段」与「显式置空」
_UNSET: Any = object()


def _utc_now() -> datetime:
    return datetime.now(UTC)


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

    def change_password(self, new_password_hash: str) -> None:
        """更换密码。

        ⚠️ 入参必须是**哈希后**的字符串（明文 → 哈希由 shared.security 完成），
        这里只做长度兜底，防止把明文误写进 password_hash。
        """
        if not new_password_hash or len(new_password_hash) < _MIN_HASH_LEN:
            raise WeakPasswordError("密码哈希不合法")
        self.password_hash = new_password_hash
        self._touch()

    def update_profile(
        self,
        *,
        display_name: Any = _UNSET,
        avatar_url: Any = _UNSET,
        bio: Any = _UNSET,
    ) -> None:
        """局部更新资料：显式传 None 表示清空该字段。"""
        if display_name is not _UNSET:
            self.display_name = display_name
        if avatar_url is not _UNSET:
            self.avatar_url = avatar_url
        if bio is not _UNSET:
            self.bio = bio
        self._touch()

    def deactivate(self) -> None:
        """停用账号（软封禁，数据保留）。"""
        self.is_active = False
        self._touch()

    def activate(self) -> None:
        """恢复账号。"""
        self.is_active = True
        self._touch()

    def _touch(self) -> None:
        self.updated_at = _utc_now()


__all__ = ["User"]
