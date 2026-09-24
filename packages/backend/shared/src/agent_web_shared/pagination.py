"""分页参数处理。"""

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def normalize_pagination(
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    *,
    max_limit: int = MAX_LIMIT,
) -> tuple[int, int]:
    """把外部传入的分页参数收敛到合法范围，返回 ``(offset, limit)``。"""
    safe_offset = max(offset, 0)
    safe_limit = min(max(limit, 1), max_limit)
    return safe_offset, safe_limit
