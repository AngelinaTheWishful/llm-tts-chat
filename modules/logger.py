"""双文件日志系统：app.log（全部日志）+ error.log（仅 ERROR）。"""

import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str = "app", debug: bool = False) -> logging.Logger:
    """初始化双文件日志系统，返回指定 logger。

    - app.log：按天滚动，记录 DEBUG 及以上全部日志
    - error.log：5MB 滚动保留 3 份，仅 ERROR 及以上
    - 控制台：debug=False 时 INFO 及以上；debug=True 时 DEBUG 及以上
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # 已初始化：仅同步控制台级别（支持 --debug 动态调整）
        if debug:
            for h in logger.handlers:
                if isinstance(h, logging.StreamHandler):
                    h.setLevel(logging.DEBUG)
        return logger

    logger.setLevel(logging.DEBUG)

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

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )

    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)

    return logger
