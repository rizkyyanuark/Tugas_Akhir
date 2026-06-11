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
FROM python:3.12-slim

# ── System Dependencies (Chromium for Selenium-based scrapers) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    git \
    curl \
    fonts-liberation \
    libnss3 \
    libnss3-dev \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Environment Configuration ──────────────────────────────────
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=300 \
    DOCKER_ENVIRONMENT=true

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/

WORKDIR /app

# ── LAYER 1: Python Dependencies (cached separately) ────────

# ── LAYER 2: Application Code ───────────────────────────────
COPY backend/package /app/package
COPY README.md /app/package/README.md
RUN mkdir -p /app/package/knowledge/etl/resources
COPY notebooks/build-graph/ieee-thesaurus.ttl /app/package/knowledge/etl/resources/ieee-thesaurus.ttl
ARG ETL_INSTALL_TEST_DEPS=true
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/package --frozen --no-dev && \
    if [ "$ETL_INSTALL_TEST_DEPS" = "true" ]; then \
        uv sync --project /app/package --frozen --group test; \
    fi

ENV PATH="/app/package/.venv/bin:$PATH" \
    PYTHONPATH="/app/package"

# ── LAYER 3: Data Directories ───────────────────────────────
# These directories are the mount points for the shared Docker volume.
# Airflow mounts the same named volume here for data persistence.
RUN mkdir -p /app/data/raw /app/data/processed

# ── Entrypoint ──────────────────────────────────────────────
ENTRYPOINT ["python", "-m", "knowledge.etl.run_worker"]
