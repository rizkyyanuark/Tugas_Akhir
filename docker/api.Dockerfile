# Backend FastAPI Service
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/
COPY --from=node:24-slim /usr/local/bin /usr/local/bin
COPY --from=node:24-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node:24-slim /usr/local/include /usr/local/include
COPY --from=node:24-slim /usr/local/share /usr/local/share

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=600 \
    UV_CONCURRENT_DOWNLOADS=2 \
    UV_HTTP_RETRIES=10 \
    HF_HOME="/app/.cache/huggingface"

RUN apt-get update && apt-get install -y --no-install-recommends \


    build-essential \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY README.md /app/README.md
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/uv.lock /app/uv.lock
COPY backend/package /app/package
COPY README.md /app/package/README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY backend/package /app/package
COPY backend/server /app/server
COPY configs /app/configs

RUN uv sync --frozen --no-dev

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5050/api/system/health || exit 1

# -- Default: Run FastAPI with Uvicorn --
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "5050", "--workers", "1"]

