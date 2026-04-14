# ══════════════════════════════════════════════════════════════
# etl-worker.Dockerfile — Isolated ETL Execution Container
# ══════════════════════════════════════════════════════════════
# Level 3 Architecture: This container does the HEAVY LIFTING.
# Airflow DockerOperator spawns this as a sibling container
# to execute scraping, transform, and load tasks.
#
# NO apache-airflow is installed here.
# All secrets are injected as environment variables by Airflow.
# ══════════════════════════════════════════════════════════════
FROM python:3.11-slim

# ── System Dependencies (Chromium for Selenium-based scrapers) ──
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

# ── Environment Configuration ──────────────────────────────────
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=300 \
    DOCKER_ENVIRONMENT=true

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# ── LAYER 1: Python Dependencies (cached separately) ────────
COPY docker/requirements-etl.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache -r /app/requirements.txt

# ── LAYER 2: Application Code ───────────────────────────────
COPY backend/package /app/package

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/package"

# ── LAYER 3: Data Directories ───────────────────────────────
# These directories are the mount points for the shared Docker volume.
# Airflow mounts the same named volume here for data persistence.
RUN mkdir -p /app/data/raw /app/data/processed

# ── Entrypoint ──────────────────────────────────────────────
ENTRYPOINT ["python", "-m", "knowledge.etl.run_worker"]
