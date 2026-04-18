import logging
import os
import sys

from loguru import logger as loguru_logger

from yunesa.utils.datetime_utils import shanghai_now

SAVE_DIR = os.getenv("SAVE_DIR") or "saves"
DATETIME = shanghai_now().strftime("%Y-%m-%d")
LOG_FILE = f"{SAVE_DIR}/logs/yunesa-{DATETIME}.log"


class LoguruHandler(logging.Handler):
    """Bridge Python logging records into a loguru handler."""

    def emit(self, record: logging.LogRecord):
        level_map = {
            logging.DEBUG: "DEBUG",
            logging.INFO: "INFO",
            logging.WARNING: "WARNING",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "CRITICAL",
        }
        level = level_map.get(record.levelno, "DEBUG")
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        loguru_logger.opt(depth=1, exception=record.exc_info).log(level, msg)


def _setup_logging_bridge():
    """Configure logging-to-loguru bridge for third-party libraries (e.g., LightRAG)."""
    loguru_handler = LoguruHandler()
    loguru_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    loguru_handler.setFormatter(formatter)

    # Bridge LightRAG logs.
    lightrag_logger = logging.getLogger("lightrag")
    lightrag_logger.addHandler(loguru_handler)
    lightrag_logger.setLevel(logging.DEBUG)
    lightrag_logger.propagate = False  # Avoid duplicate logs.

    # Bridge other common third-party libraries (reduce level to lower noise).
    for lib in ["httpx", "openai", "neo4j", "urllib3"]:
        lib_logger = logging.getLogger(lib)
        lib_logger.addHandler(loguru_handler)
        lib_logger.setLevel(logging.WARNING)
        lib_logger.propagate = False


def setup_logger(name, level="DEBUG", console=True):
    """Set up logger using loguru."""
    os.makedirs(f"{SAVE_DIR}/logs", exist_ok=True)

    # Remove default handlers.
    loguru_logger.remove()

    # Add file logging (no color).
    loguru_logger.add(
        LOG_FILE,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {file}:{line} - {message}",
        encoding="utf-8",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )

    # Add console logging (with color).
    if console:
        loguru_logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:MM-DD HH:mm:ss}</green> "
                "<level>{level}</level> "
                "<cyan>{file}:{line}</cyan>: "
                "<level>{message}</level>"
            ),
            colorize=True,
            enqueue=True,
        )

    return loguru_logger


# Set root logger.
logger = setup_logger("Yunesa")

# Initialize logging bridge.
_setup_logging_bridge()

__all__ = ["logger"]
