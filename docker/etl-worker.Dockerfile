FROM python:3.12-slim

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

ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=600 \
    UV_CONCURRENT_DOWNLOADS=2 \
    UV_HTTP_RETRIES=10 \
    DOCKER_ENVIRONMENT=true


COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/

WORKDIR /app

COPY backend/package /app/package
COPY README.md /app/package/README.md
COPY notebooks/build-graph/src /app/kg-src
RUN mkdir -p /app/package/yunesa/etl/resources
COPY notebooks/build-graph/ieee-thesaurus.ttl /app/package/yunesa/etl/resources/ieee-thesaurus.ttl
COPY notebooks/build-graph/ieee-taxonomy.ttl /app/package/yunesa/etl/resources/ieee-taxonomy.ttl
COPY notebooks/build-graph/config/concept_aliases.yml /app/package/yunesa/etl/resources/concept_aliases.yml
ARG ETL_INSTALL_TEST_DEPS=true
ARG ETL_INSTALL_KG_DEPS=false
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project /app/package --frozen --no-dev && \
    if [ "$ETL_INSTALL_TEST_DEPS" = "true" ]; then \
        uv sync --project /app/package --frozen --group test; \
    fi && \
    if [ "$ETL_INSTALL_KG_DEPS" = "true" ]; then \
        uv sync --project /app/package --frozen --group kg; \
    fi

ENV PATH="/app/package/.venv/bin:$PATH" \
    PYTHONPATH="/app/package:/app/kg-src"

RUN mkdir -p /app/data/raw /app/data/processed
ENTRYPOINT ["python", "-m", "yunesa.etl.run_worker"]
