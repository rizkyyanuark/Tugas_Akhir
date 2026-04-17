#!/bin/bash
set -e

# Support emojis in terminal
export LC_ALL=en_US.UTF-8

echo -e "\033[36m🚀 Initializing UNESA Knowledge Graph project...\033[0m"
echo -e "\033[36m==============================================\033[0m"

# Check if .env file exists
if [ -f ".env" ]; then
    echo -e "\033[32m✅ .env file already exists. Skipping environment setup.\033[0m"
else
    echo -e "\033[33m📝 .env file not found. Let's set up your environment variables.\033[0m\n"

    # Get SUPABASE Config
    echo -e "\033[33m🔑 Supabase Database configuration required\033[0m"
    echo -e "\033[90mNote: Press Ctrl+C at any time to cancel\033[0m\n"

    while [ -z "$SUPABASE_URL" ]; do
        read -p "Please enter your SUPABASE_URL: " SUPABASE_URL
    done

    while [ -z "$SUPABASE_KEY" ]; do
        read -p "Please enter your SUPABASE_KEY (anon/publishable): " SUPABASE_KEY
    done

    # Get GROQ API KEY
    echo -e "\n\033[33m🧠 Groq API Key required for LLM processing\033[0m"
    while [ -z "$GROQ_API_KEY" ]; do
        read -p "Please enter your GROQ_API_KEY: " GROQ_API_KEY
    done

    # Get TELEGRAM BOT TOKEN
    echo -e "\n\033[33m🤖 Telegram Bot Token (optional)\033[0m"
    read -p "Please enter your TELEGRAM_BOT_TOKEN (press Enter to skip): " TELEGRAM_TOKEN

    # Create .env file
    cat > .env << EOL
# 1. Supabase Database Configuration
SUPABASE_URL=$SUPABASE_URL
SUPABASE_KEY=$SUPABASE_KEY

# 2. AI / LLM API Keys
GROQ_API_KEY=$GROQ_API_KEY

# 3. Infrastructure Defaults
PASSWORD=71509325
NEO4J_AUTH=neo4j/71509325
NEO4J_PASSWORD=71509325
GRAFANA_ADMIN_PASSWORD=71509325
AIRFLOW_ADMIN_PASSWORD=71509325
POSTGRES_PASSWORD=71509325
AIRFLOW_FERNET_KEY=dG9wU2VqcmV0RmVybmV0S2V5MTIzNDU2Nzg5MEFCQ0Q=
EOL

    if [ -n "$TELEGRAM_TOKEN" ]; then
        echo -e "\n# 4. Telegram Bot\nTELEGRAM_BOT_TOKEN=$TELEGRAM_TOKEN" >> .env
    fi

    echo -e "\033[32m✅ .env file created successfully! You can edit it later to add BrightData/SerpAPI keys.\033[0m"
fi

echo -e "\n\033[36m📂 Creating Docker volume directories...\033[0m"
echo -e "\033[36m======================================\033[0m"

VOLUME_DIRS=(
    "docker/volumes/postgres/data"
    "docker/volumes/milvus/etcd"
    "docker/volumes/milvus/minio"
    "docker/volumes/milvus/milvus"
    "docker/volumes/neo4j/data"
    "docker/volumes/neo4j/logs"
    "docker/volumes/neo4j/plugins"
    "docker/volumes/neo4j/import"
    "docker/volumes/prometheus/data"
    "docker/volumes/grafana/data"
    "docker/volumes/redis/data"
    "logs"
)

for dir in "${VOLUME_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo -e "\033[32m✅ Created $dir\033[0m"
    else
        echo -e "\033[90mℹ️ $dir already exists\033[0m"
    fi
done

echo -e "\n\033[36m📦 Pulling Docker images...\033[0m"
echo -e "\033[36m=========================\033[0m"

# List of Docker images to pull
IMAGES=(
    "ghcr.io/astral-sh/uv:latest"
    "node:20-alpine"
    "nginx:alpine"
    "postgres:13"
    "redis:7-alpine"
    "coreos/etcd:v3.5.5"
    "minio/minio:RELEASE.2023-03-20T20-16-18Z"
    "milvusdb/milvus:v2.4.9"
    "neo4j:5.15"
    "apache/airflow:2.8.0-python3.10"
    "mcr.microsoft.com/playwright/python:v1.40.0-jammy"
    "prom/prometheus:latest"
    "grafana/grafana:10.2.2"
    "google/cadvisor:latest"
    "prom/node-exporter:latest"
)

# Make pull script executable
chmod +x scripts/pull_image.sh

# Pull each image
for image in "${IMAGES[@]}"; do
    echo -e "\033[33m🔄 Pulling ${image}...\033[0m"
    if bash scripts/pull_image.sh "$image"; then
        echo -e "\033[32m✅ Successfully pulled ${image}\033[0m"
    else
        echo -e "\033[31m❌ Failed to pull ${image}\033[0m"
        exit 1
    fi
done

echo -e "\n\033[32m🎉 Initialization complete!\033[0m"
echo -e "\033[32m==========================\033[0m"
echo -e "\033[36mYou can now run: docker compose up -d --build\033[0m"
echo -e "\033[36mTo include optional stacks, run:\033[0m"
echo -e "\033[90m  docker compose --profile etl up -d\033[0m"
echo -e "\033[90m  docker compose --profile monitoring up -d\033[0m"
