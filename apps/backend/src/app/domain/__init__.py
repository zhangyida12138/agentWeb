"""领域层：实体、值对象、领域服务与仓储接口，不依赖任何框架。"""

from app.domain.exceptions import DomainError

__all__ = ["DomainError"]
