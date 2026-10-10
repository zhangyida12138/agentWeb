from __future__ import annotations

import sys
from contextvars import ContextVar
from uuid import uuid4

from loguru import logger

# 贯穿单次请求的唯一 ID（中间件写入，日志读取）
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

def _format_record(record: dict) -> str:
    """把 request_id 注入日志格式模板（从 ContextVar 读，自动随请求切换）。"""

    record["extra"]["request_id"] = request_id_var.get()
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "[<magenta>{extra[request_id]}</magenta>] "
        "<level>{message}</level>"
        "{exception}\n"
    )

def generate_request_id() -> str:
    """生成短 request_id（不带横杠的 hex，header 好看点）。"""

    return uuid4().hex

def setup_logging(debug: bool = False) -> None:
    """应用启动时调用一次，替换默认 handler。"""

    logger.remove()

    # 控制台 handler（生产可以追加 JSON handler，这里先简单 console）
    logger.add(
        sys.stderr,
        level="DEBUG" if debug else "INFO",
        format=_format_record,
        backtrace=debug,
        diagnose=debug,
        enqueue=True,
        catch=True,
    )

    if debug:
        logger.debug("Logging initialized in DEBUG mode")
    else:
        logger.info("Logging initialized in INFO mode")
