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
FROM python:3.12-slim
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

# ── LAYER 1: Core Dependency Resolution (MAX CACHE) ─────────
# Copy ONLY manifest files to resolve external dependencies.
# This layer includes the 2GB+ AI libraries (PyTorch, etc.).
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/uv.lock /app/uv.lock
COPY backend/package/pyproject.toml /app/package/pyproject.toml

# Create a skeleton directory structure for the local 'Yunesa' package.
# This allows 'uv sync' to "install" the local package in editable mode 
# without needing the actual source code yet.
RUN mkdir -p /app/package/yunesa && touch /app/package/yunesa/__init__.py

# Initial sync - This layer is CACHED until dependencies change.
# Changes to your code will NOT trigger this heavy download step.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev 2>/dev/null || uv lock && uv sync --no-dev

# -- Add venv to PATH --
ENV PATH="/app/.venv/bin:$PATH"

# ── LAYER 2: Actual Source Code (BUSTS on code change) ──────
# Now copy the real source code. This is very fast (milliseconds).
COPY backend/package /app/package
COPY backend/server /app/server
COPY configs /app/configs

# Final fast sync to link actual source files correctly.
# This step is nearly instant because all heavy lifting is already cached.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# -- Expose Port --
EXPOSE 5050

# -- Health Check --
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5050/health || exit 1

# -- Default: Run FastAPI with Uvicorn --
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "1"]
