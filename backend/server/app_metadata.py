"""Application identity and API metadata.

Keep product identity in one explicit module instead of hiding it in
``server.utils``. This module is intentionally small and stable because it is
used by FastAPI startup, the API landing page, and startup logging.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from yunesa import get_version

APP_NAME = "YUNESA"
API_TITLE = "YUNESA API"
API_DESCRIPTION = "Knowledge Discovery System API"
AUTHOR = "Rizky Yanuar Kristianto"
DOCS_URL = "/doc"
REDOC_URL = "/redoc"
HEALTH_URL = "/api/system/health"

_BANNER_TEMPLATE = r"""
__   ___   _ _   _ _____ ____    _
\ \ / / | | | \ | | ____/ ___|  / \
 \ V /| | | |  \| |  _| \___ \ / _ \
  | | | |_| | |\  | |___ ___) / ___ \
  |_|  \___/|_| \_|_____|____/_/   \_\
                                      v{version}
""".strip("\n")


@dataclass(frozen=True)
class ApiMetadata:
    title: str
    description: str
    version: str
    status: str
    environment: str
    author: str
    docs_url: str
    health_url: str
    timestamp: str


def runtime_environment() -> str:
    """Return the active runtime environment label."""
    return (
        os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("YUNESA_ENV")
        or "development"
    )


def get_yunesa_banner(version: str | None = None) -> str:
    """Return the startup/landing-page banner."""
    return _BANNER_TEMPLATE.format(version=version or get_version())


def get_api_metadata() -> ApiMetadata:
    """Build current API metadata for human-readable surfaces."""
    return ApiMetadata(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=get_version(),
        status="Running",
        environment=runtime_environment(),
        author=AUTHOR,
        docs_url=DOCS_URL,
        health_url=HEALTH_URL,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

