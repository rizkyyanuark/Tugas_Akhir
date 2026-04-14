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
from fastapi import FastAPI, Request, status, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from server.routers import router
from server.utils.lifespan import lifespan
from server.utils.auth_middleware import is_public_path
from server.utils.common_utils import setup_logging
from server.utils.access_log_middleware import AccessLogMiddleware

import logging
logger = logging.getLogger("ta-backend")

# 设置日志配置
setup_logging()

RATE_LIMIT_MAX_ATTEMPTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_ENDPOINTS = {("/api/auth/token", "POST")}

# In-memory login attempt tracker to reduce brute-force exposure per worker
_login_attempts: defaultdict[str, deque[float]] = defaultdict(deque)
_attempt_lock = asyncio.Lock()

app = FastAPI(lifespan=lifespan)
# 所有业务接口统一挂载到 /api，具体分组在 server.routers 中集中注册。
app.include_router(router, prefix="/api")

# CORS 设置
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
                        content={"detail": "登录尝试过于频繁，请稍后再试"},
                        headers={"Retry-After": str(retry_after)},
                    )

                attempt_history.append(now)

            response = await call_next(request)

            if response.status_code < 400:
                async with _attempt_lock:
                    _login_attempts.pop(client_ip, None)

            return response

        return await call_next(request)


# 鉴权中间件
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if is_public_path(path):
            return await call_next(request)
        if not path.startswith("/api"):
            return await call_next(request)
        return await call_next(request)

# 添加访问日志中间件（记录请求处理时间）
app.add_middleware(AccessLogMiddleware)

# 添加鉴权中间件
app.add_middleware(LoginRateLimitMiddleware)
app.add_middleware(AuthMiddleware)


# ── Strwythura Webhook Integration ──────────────────────────────
class WebhookPayload(BaseModel):
    task_name: str = Field(..., description="Name of the Airflow task/DAG")
    batch_id: str = Field(..., description="Unique batch identifier")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp"
    )
    status: str = Field(default="ETL_SUCCESS", description="Pipeline completion status")

class TriggerResponse(BaseModel):
    accepted: bool
    message: str
    batch_id: str

async def run_kg_pipeline(payload: WebhookPayload):
    logger.info(f"🚀 Starting KG pipeline for batch: {payload.batch_id}")
    try:
        from knowledge.kg.services.kg_pipeline import KGPipeline
        pipeline = KGPipeline(test_mode=False) 
        summary = pipeline.run()
        logger.info(f"✅ KG pipeline completed for batch: {payload.batch_id}")
    except Exception as e:
        logger.error(f"❌ KG pipeline failed for batch {payload.batch_id}: {e}")
        raise
@app.post("/webhook/trigger", response_model=TriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def webhook_trigger(payload: WebhookPayload, background_tasks: BackgroundTasks):
    logger.info(f"📥 Received Webhook Trigger from Airflow: {payload.dict()}")
    background_tasks.add_task(run_kg_pipeline, payload)
    return TriggerResponse(
        accepted=True,
        message=f"Batch {payload.batch_id} accepted. Processing in background.",
        batch_id=payload.batch_id
    )

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/load balancer probes."""
    return {"status": "healthy", "service": "kg-backend", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["server", "package"],
    )
