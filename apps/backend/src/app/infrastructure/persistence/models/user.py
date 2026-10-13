"""identity 上下文的 ORM 模型。

⚠️ 模型**不是**领域实体：
    它是「表结构 + 索引 + 约束」的映射，业务规则一律住在
    ``domain/identity/entities.py``；两者由 ``mappers/user.py`` 显式翻译。
    直接改模型绕开实体，等于把不变量丢掉。

字段顺序有讲究：``MappedAsDataclass`` 会把带默认值的字段排到后面，
而无默认值的字段必须排在前面（dataclass 的硬性要求）。
``base.py`` 里 mixin 用 sort_order 把 id 提到最前（-100）、时间戳压到最后（100/101），
所以本类只需按「必填 → 选填」的顺序声明即可。
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.identity.value_objects import EMAIL_MAX_LEN, USERNAME_MAX_LEN
from app.infrastructure.persistence.base import Base, IDMixin, TimestampMixin

DISPLAY_NAME_MAX_LEN = 64
AVATAR_URL_MAX_LEN = 512


class UserModel(Base, IDMixin, TimestampMixin):
    """users 表。"""

    __tablename__ = "users"

    # 长度上限直接复用领域值对象的常量：两处若各写一遍，早晚会漂移；
    # 数据库这一层是最后一道闸，用于挡住绕过用例直接写库的场景
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LEN), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LEN), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_MAX_LEN))

    avatar_url: Mapped[str | None] = mapped_column(String(AVATAR_URL_MAX_LEN), default=None)
    bio: Mapped[str | None] = mapped_column(Text, default=None)
    # server_default 让「直接 INSERT 不带 is_active」也能得到 true，
    # 例如将来手工修数据或数据迁移脚本
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    def __repr__(self) -> str:
        """手写 __repr__ 覆盖 dataclass 自动生成的那个。

        MappedAsDataclass 默认会把**所有**字段打进 repr，而 fastapi/uvicorn 的
        异常日志会打印对象——密码哈希就这样进了日志文件。哈希虽然不能直接还原明文，
        但它是「离线爆破」的输入，不该出现在日志里。
        """
        return (
            f"<UserModel id={self.id!r} email={self.email!r} "
            f"username={self.username!r} is_active={self.is_active!r}>"
        )


__all__ = ["AVATAR_URL_MAX_LEN", "DISPLAY_NAME_MAX_LEN", "UserModel"]
