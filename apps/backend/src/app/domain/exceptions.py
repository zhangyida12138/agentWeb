"""领域异常基类。

⚠️ 铁律：domain 层不得 import 任何框架（FastAPI / SQLAlchemy / Pydantic），
本模块是这条规则的落点之一——所以这里只放**纯 Python** 的异常定义，
HTTP 状态码推导、响应信封、全局处理器统统留在 ``core/exceptions.py``。

为什么基类必须在这里而不是 core：
    若 ``domain/identity/exceptions.py`` 去继承 ``core.exceptions.DomainError``，
    就会顺着 core → fastapi 把框架拖进领域层，破坏「领域可脱离框架独立测试」。
"""

from __future__ import annotations

from typing import Any

# code 编码规范：HTTP 状态码 × 100 + 同类序号，例如
#   40001 → 400 类；40900 → 409 类；50000 → 500 类
_CODE_MIN = 10000
_CODE_MAX = 60000


class DomainError(Exception):
    """领域层 / 全局异常基类。所有业务异常必须继承它。"""

    def __init__(
        self,
        code: int,
        message: str,
        data: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        # 允许显式指定 HTTP 状态；否则从 code 的前 3 位推导（40900 → 409）
        self.http_status = http_status or (
            code // 100 if _CODE_MIN <= code < _CODE_MAX else 500
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code}, message={self.message!r})"


__all__ = ["DomainError"]
