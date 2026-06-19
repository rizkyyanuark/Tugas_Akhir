# ══════════════════════════════════════════════════════════════
# airflow.Dockerfile — Pure Orchestrator (Level 3 Architecture)
# ══════════════════════════════════════════════════════════════
# Airflow does NOT run ETL code directly. All heavy lifting runs
# in isolated etl-worker containers via DockerOperator.
# Requires: docker-ce-cli (debug) + Docker SDK + /var/run/docker.sock.
# ══════════════════════════════════════════════════════════════
FROM apache/airflow:3.1.7-python3.12

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN mkdir -p /opt/airflow/src /opt/airflow/data /opt/airflow/notebooks \
    && chown -R airflow:0 /opt/airflow/src \
    && chown -R airflow:0 /opt/airflow/data

ARG CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-3.1.7/constraints-3.12.txt"

RUN uv pip install --system --no-cache \
    "apache-airflow==3.1.7" \
    "apache-airflow-providers-docker" \
    "apache-airflow-providers-fab" \
    "apache-airflow-providers-ssh" \
    "apache-airflow-providers-standard" \
    "asyncpg" \
    "requests" \
    "psycopg2-binary" \
    --constraint "${CONSTRAINT_URL}"

USER airflow
