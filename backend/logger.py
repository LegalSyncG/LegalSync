import logging
from logging import Logger as BaseLogger
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

class Logger:
    _logger: BaseLogger = None

    @staticmethod
    def get_logger(name: str = "legalsync") -> BaseLogger:
        if Logger._logger is not None:
            return Logger._logger

        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.propagate = False 

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        Logger._logger = logger
        return logger

logger = Logger.get_logger()
