"""密码哈希与 JWT 签发/校验。

无状态工具，与框架、数据库无关，供各限界上下文复用。
依赖：bcrypt（慢哈希）、PyJWT（签发/校验）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

DEFAULT_ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 60

# bcrypt 只看前 72 字节，超长会抛错（新版本）或静默截断（旧版本），这里统一显式校验
_BCRYPT_MAX_BYTES = 72


def _encode_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        msg = "密码过长：bcrypt 最多接受 72 字节，请限制长度或先做预哈希"  # noqa: RUF001
        raise ValueError(msg)
    return raw


def hash_password(password: str, *, rounds: int = 12) -> str:
    """生成 bcrypt 哈希（随机盐写入结果串，相同密码也不同哈希）。"""
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """恒定时间比对明文与哈希；哈希串损坏或密码超长时返回 False。"""
    try:
        return bcrypt.checkpw(_encode_password(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    subject: str | int,
    *,
    secret_key: str,
    algorithm: str = DEFAULT_ALGORITHM,
    expires_minutes: int = DEFAULT_EXPIRE_MINUTES,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发 JWT。

    - sub 强制转字符串（JWT 规范要求）
    - 自动带 jti / iat / exp，便于吊销与防重放
    - extra_claims 不能覆盖关键字段（sub/jti/iat/exp）
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if extra_claims:
        payload.update({k: v for k, v in extra_claims.items() if k not in payload})
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_token(
    token: str,
    *,
    secret_key: str,
    algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """校验并解出 payload。

    - algorithms 显式限定（默认仅 HS256），防 alg=none 算法混淆攻击
    - 过期 / 签名不符会抛 jwt.InvalidTokenError，由调用方转为业务异常
    """
    return jwt.decode(token, secret_key, algorithms=algorithms or [DEFAULT_ALGORITHM])


__all__ = [
    "DEFAULT_ALGORITHM",
    "DEFAULT_EXPIRE_MINUTES",
    "create_access_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
