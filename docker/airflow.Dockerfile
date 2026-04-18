# ══════════════════════════════════════════════════════════════
# airflow.Dockerfile — Pure Orchestrator (Level 3 Architecture)
# ══════════════════════════════════════════════════════════════
# Airflow does NOT run ETL code directly. All heavy work runs
# in isolated etl-worker containers via DockerOperator.
# ══════════════════════════════════════════════════════════════
FROM apache/airflow:3.1.7-python3.12

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN mkdir -p /opt/airflow/src /opt/airflow/data /opt/airflow/notebooks \
    && chown -R airflow:0 /opt/airflow/src \
    && chown -R airflow:0 /opt/airflow/data

ARG CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-3.1.7/constraints-3.12.txt"

RUN uv pip install --system --no-cache \
    "apache-airflow-providers-docker" \
    "apache-airflow-providers-fab" \
    "apache-airflow-providers-ssh" \
    "apache-airflow-providers-standard" \
    "requests" \
    "psycopg2-binary" \
    --constraint "${CONSTRAINT_URL}"

USER airflow
