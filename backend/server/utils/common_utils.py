"""Common utility functions"""

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from yunesa.storage.postgres.models_business import OperationLog, User


def setup_logging():
    """Configure application logging format"""
    # Configure logging format
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S", force=True
    )

    # Ensure uvicorn logs use the same format
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_access_logger = logging.getLogger("uvicorn.access")

    # Disable default uvicorn access logs (since we use custom middleware)
    uvicorn_access_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(fmt="%(asctime)s %(levelname)s: %(message)s", datefmt="%m-%d %H:%M:%S")

    # Set formatter for uvicorn main logger
    for handler in uvicorn_logger.handlers:
        handler.setFormatter(formatter)


async def log_operation(db: Session, user_id: int, operation: str, details: str = None, request: Request = None):
    """Record user operation logs"""
    try:
        ip_address = None
        if request:
            ip_address = request.client.host if request.client else None

        log = OperationLog(user_id=user_id, operation=operation, details=details, ip_address=ip_address)
        db.add(log)
        await db.commit()
    except Exception:
        # Logging failure should not affect main business logic
        pass


def get_user_dict(user: User, include_password: bool = False) -> dict:
    """Get user dictionary representation"""
    return user.to_dict(include_password)


def convert_serializable(obj):
    """Convert object to serializable format"""
    if isinstance(obj, list | tuple):
        return [convert_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: convert_serializable(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return convert_serializable(vars(obj))
    return obj
