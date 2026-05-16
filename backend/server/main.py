import asyncio
import os
import sys

# ==============================================================================
# Windows psycopg ProactorEventLoop fix
# ==============================================================================
if sys.platform == "win32":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import time
from collections import defaultdict, deque

import uvicorn
from fastapi import FastAPI, Request, status
from datetime import datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from server.app_metadata import API_DESCRIPTION, API_TITLE, DOCS_URL, REDOC_URL, get_api_metadata
from server.presentation import render_api_homepage
from server.routers import router
from server.utils.lifespan import lifespan
from server.utils.auth_middleware import is_public_path
from server.utils.common_utils import setup_logging
from server.utils.access_log_middleware import AccessLogMiddleware
from yunesa import get_version

import logging
logger = logging.getLogger("ta-backend")

# Setup logging configuration
setup_logging()

RATE_LIMIT_MAX_ATTEMPTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_ENDPOINTS = {("/api/auth/token", "POST")}

# In-memory login attempt tracker to reduce brute-force exposure per worker
_login_attempts: defaultdict[str, deque[float]] = defaultdict(deque)
_attempt_lock = asyncio.Lock()

app = FastAPI(
    lifespan=lifespan,
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=get_version(),
    docs_url=DOCS_URL,
    redoc_url=REDOC_URL,
)
# All business interfaces are uniformly mounted to /api, and specific groups are centrally registered in server.routers.
app.include_router(router, prefix="/api")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _extract_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        normalized_path = request.url.path.rstrip("/") or "/"
        request_signature = (normalized_path, request.method.upper())

        if request_signature in RATE_LIMIT_ENDPOINTS:
            client_ip = _extract_client_ip(request)
            now = time.monotonic()

            async with _attempt_lock:
                attempt_history = _login_attempts[client_ip]

                while attempt_history and now - attempt_history[0] > RATE_LIMIT_WINDOW_SECONDS:
                    attempt_history.popleft()

                if len(attempt_history) >= RATE_LIMIT_MAX_ATTEMPTS:
                    retry_after = int(max(1, RATE_LIMIT_WINDOW_SECONDS - (now - attempt_history[0])))
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={"detail": "Too many login attempts, please try again later"},
                        headers={"Retry-After": str(retry_after)},
                    )

                attempt_history.append(now)

            response = await call_next(request)

            if response.status_code < 400:
                async with _attempt_lock:
                    _login_attempts.pop(client_ip, None)

            return response

        return await call_next(request)


# Authentication middleware
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if is_public_path(path):
            return await call_next(request)
        if not path.startswith("/api"):
            return await call_next(request)
        return await call_next(request)

# Add access log middleware (record request processing time)
app.add_middleware(AccessLogMiddleware)

# Add authentication and rate limit middleware
app.add_middleware(LoginRateLimitMiddleware)
app.add_middleware(AuthMiddleware)

@app.get("/", response_class=HTMLResponse, tags=["Root"])
async def root(request: Request):
    """Human-readable API landing page."""
    base_url = str(request.base_url).rstrip("/")
    return render_api_homepage(get_api_metadata(), base_url)


@app.get("/docs", include_in_schema=False)
async def legacy_docs_redirect():
    return RedirectResponse(url="/doc", status_code=308)

async def health_check():
    """Health check endpoint for Docker/load balancer probes."""
    return {"status": "healthy", "service": "kg-backend", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=5050,
        reload=True,
        reload_dirs=["server", "package"],
    )
