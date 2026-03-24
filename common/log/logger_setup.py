import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: ^8}</level> | "
    "process [<cyan>{process}</cyan>]:<cyan>{thread}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def add_module_logger(module_prefix: str):
    """
    Configures logging for a module with console and file outputs.

    Args:
        module_prefix (str): Prefix for log file names (e.g., "module_name").
    """
    logger.configure(extra={"request_id": ''})
    logger.remove()

    # Console output
    logger.add(
        sys.stdout,
        format=LOG_FORMAT,
        level="INFO",
        backtrace=False,
        colorize=True,
    )

    # Regular log file
    logger.add(
        _LOG_DIR / f"{module_prefix}_log_{{time:YYYY-MM-DD}}.log",
        format=LOG_FORMAT,
        level="INFO",
        rotation=lambda message, file: (
                os.stat(file.name).st_size > 10 * 1024 * 1024
                or datetime.now(tz=timezone.utc).date() != datetime.fromtimestamp(os.path.getctime(file.name)).date()
        ),
        retention="30 days",
        encoding="utf-8",
        compression="zip",
        enqueue=True,
    )

    # Error log file
    logger.add(
        _LOG_DIR / f"{module_prefix}_error_{{time:YYYY-MM-DD}}.log",
        format=LOG_FORMAT,
        level="ERROR",
        rotation=lambda message, file: (
                os.stat(file.name).st_size > 10 * 1024 * 1024
                or datetime.now(tz=timezone.utc).date() != datetime.fromtimestamp(os.path.getctime(file.name)).date()
        ),
        retention="30 days",
        encoding="utf-8",
        compression="zip",
        enqueue=True,
    )
