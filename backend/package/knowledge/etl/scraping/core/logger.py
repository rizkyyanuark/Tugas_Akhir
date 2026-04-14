import sys
from loguru import logger

# Remove default handler
logger.remove()

# Add standard stdout handler with clean formatting
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

# Optional: Add file logger if needed (e.g. for long running background tasks)
# logger.add("logs/scraping_{time}.log", rotation="10 MB", level="DEBUG")

# Export standard logger
__all__ = ["logger"]
