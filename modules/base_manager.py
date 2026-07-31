"""BaseManager：所有 Manager/Client 的基类，提供统一日志接口。"""

from modules.logger import setup_logger


class BaseManager:
    """所有 Manager/Client 的基类，提供日志接口。"""

    def __init__(self, logger_name: str | None = None):
        self.logger = setup_logger(logger_name or self.__class__.__name__)

    def log(self, level: str, message: str) -> None:
        """按级别记录日志。

        Args:
            level: "debug" / "info" / "warning" / "error" / "critical"
            message: 日志内容
        """
        level = level.lower()
        log_func = getattr(self.logger, level, self.logger.info)
        log_func(message)
