"""双文件日志系统：app.log（全部日志）+ error.log（仅 ERROR）。

v1.3.0（Q2）：文件 Handler 在模块级缓存并跨 logger 共享，
避免每个 logger 各建一套指向同一文件的 Handler（轮转竞争 + 句柄堆积）。
"""

import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# 模块级共享的文件 Handler（首次初始化后复用）
_file_handlers: list[logging.Handler] = []


def _ensure_file_handlers() -> list[logging.Handler]:
    """创建（或复用）共享的文件 Handler。"""
    global _file_handlers
    if _file_handlers:
        return _file_handlers

    app_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / "app.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FMT))

    error_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "error.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FMT))

    _file_handlers = [app_handler, error_handler]
    return _file_handlers


def setup_logger(name: str = "app", debug: bool = False) -> logging.Logger:
    """初始化双文件日志系统，返回指定 logger。

    - app.log：按天滚动，记录 DEBUG 及以上全部日志
    - error.log：5MB 滚动保留 3 份，仅 ERROR 及以上
    - 控制台：debug=False 时 INFO 及以上；debug=True 时 DEBUG 及以上
    - 文件 Handler 全局共享（Q2），仅控制台 Handler 按 logger 独立
    """
    logger = logging.getLogger(name)

    # 附加共享文件 Handler（避免重复附加）
    for h in _ensure_file_handlers():
        if h not in logger.handlers:
            logger.addHandler(h)

    # 控制台 Handler（按 logger 独立，便于 debug 级别单独调整）。
    # 注意：TimedRotatingFileHandler/RotatingFileHandler 继承自 StreamHandler，
    # 必须用精确类型判断，避免把文件 Handler 误当控制台 Handler。
    console_handler = None
    for h in logger.handlers:
        if type(h) is logging.StreamHandler:
            console_handler = h
            break
    if console_handler is None:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(console_handler)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)

    logger.setLevel(logging.DEBUG)
    return logger
