"""仓储接口的具体实现（依赖倒置：接口在 domain，实现在这里）。"""

from app.infrastructure.persistence.repositories.user import SqlUserRepository

__all__ = ["SqlUserRepository"]
