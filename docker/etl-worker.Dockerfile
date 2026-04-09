# ══════════════════════════════════════════════════════════════
# etl-worker.Dockerfile — Isolated ETL Execution Container
# ══════════════════════════════════════════════════════════════
# Level 3 Architecture: This container does the HEAVY LIFTING.
# Airflow DockerOperator spawns this as a sibling container
# to execute scraping, transform, and load tasks.
#
# NO apache-airflow is installed here.
# ══════════════════════════════════════════════════════════════
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    git \
    curl \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/uv.lock /app/uv.lock
COPY backend/package /app/package

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev 2>/dev/null || uv lock && uv sync --no-dev


ENV PATH="/app/.venv/bin:$PATH"

COPY notebooks /app/notebooks
COPY configs /app/configs

RUN mkdir -p /app/data/raw /app/data/processed

ENTRYPOINT ["python", "-m", "ta_backend_core.knowledge.etl.run_worker"]
