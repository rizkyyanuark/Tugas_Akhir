# ══════════════════════════════════════════════════════════════
# api.Dockerfile — Backend FastAPI Service (Yuxi-style)
# ══════════════════════════════════════════════════════════════
# Build strategy:
#   1. Install system deps (cached forever)
#   2. Copy pyproject.toml + package/ → `uv sync` (cached until deps change)
#   3. Copy server/ last (only this layer busts on code changes)
#
# This means editing server/main.py does NOT re-download 2GB of
# PyTorch/SpaCy/GLiNER dependencies. Docker build goes from
# 15 minutes → 5 seconds on code-only changes.
# ══════════════════════════════════════════════════════════════
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# -- Working Directory --
WORKDIR /app

# -- Environment --
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=300 \
    HF_HOME="/app/.cache/huggingface"

# -- System Dependencies --
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── LAYER 1: Project manifest + core package (CACHED) ───────
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/uv.lock /app/uv.lock
COPY backend/package /app/package

# Install all dependencies via uv sync (uses Docker cache mount)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev 2>/dev/null || uv lock && uv sync --no-dev

# -- Add venv to PATH --
ENV PATH="/app/.venv/bin:$PATH"

# ── LAYER 2: Server code (BUSTS on every code change) ──────
COPY backend/server /app/server
COPY configs /app/configs

# -- Expose Port --
EXPOSE 8000

# -- Health Check --
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# -- Default: Run FastAPI with Uvicorn --
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
