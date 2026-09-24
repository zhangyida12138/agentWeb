"""AgentWeb 后端公共包。

这里只放与框架、数据库无关的无状态工具，供 apps/backend 等应用复用。
"""

from agent_web_shared.pagination import DEFAULT_LIMIT, MAX_LIMIT, normalize_pagination

__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "normalize_pagination"]
