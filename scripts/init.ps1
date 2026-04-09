# Tugas Akhir Initialization Script for PowerShell
# This script helps set up the environment for the Airflow ETL to Supabase project
# Note: API keys will be visible during input - use with care

Write-Host "🚀 Initializing UNESA Knowledge Graph project..." -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# Check if .env file exists
if (Test-Path ".env") {
    Write-Host "✅ .env file already exists. Skipping environment setup." -ForegroundColor Green
} else {
    Write-Host "📝 .env file not found. Let's set up your environment variables." -ForegroundColor Yellow
    Write-Host ""

    # Get SUPABASE URL
    Write-Host "🔑 Supabase Database configuration required" -ForegroundColor Yellow
    Write-Host "Note: Press Ctrl+C at any time to cancel" -ForegroundColor Gray
    Write-Host ""
    do {
        $supabaseUrl = Read-Host "Please enter your SUPABASE_URL"
    } while ([string]::IsNullOrEmpty($supabaseUrl))

    do {
        $supabaseKey = Read-Host "Please enter your SUPABASE_KEY (anon/publishable)"
    } while ([string]::IsNullOrEmpty($supabaseKey))

    # Get GROQ API KEY
    Write-Host ""
    Write-Host "🧠 Groq API Key required for LLM processing" -ForegroundColor Yellow
    do {
        $groqApiKey = Read-Host "Please enter your GROQ_API_KEY"
    } while ([string]::IsNullOrEmpty($groqApiKey))

    # Get TELEGRAM BOT TOKEN (Optional)
    Write-Host ""
    Write-Host "🤖 Telegram Bot Token (optional)" -ForegroundColor Yellow
    $telegramToken = Read-Host "Please enter your TELEGRAM_BOT_TOKEN (press Enter to skip)"

    # Create .env file
    $envContent = @"
# 1. Supabase Database Configuration
SUPABASE_URL=$supabaseUrl
SUPABASE_KEY=$supabaseKey

# 2. AI / LLM API Keys
GROQ_API_KEY=$groqApiKey

# 3. Infrastructure Defaults
PASSWORD=71509325
NEO4J_AUTH=neo4j/71509325
NEO4J_PASSWORD=71509325
GRAFANA_ADMIN_PASSWORD=71509325
AIRFLOW_ADMIN_PASSWORD=71509325
POSTGRES_PASSWORD=71509325
AIRFLOW_FERNET_KEY=dG9wU2VqcmV0RmVybmV0S2V5MTIzNDU2Nzg5MEFCQ0Q=
"@

    if (-not [string]::IsNullOrEmpty($telegramToken)) {
        $envContent += "`n`n# 4. Telegram Bot`nTELEGRAM_BOT_TOKEN=$telegramToken"
    }

    $envContent | Out-File -FilePath ".env" -Encoding UTF8
    Write-Host "✅ .env file created successfully! You can edit it later to add BrightData/SerpAPI keys." -ForegroundColor Green

    # Clear the variables from memory
    Remove-Variable -Name "supabaseUrl" -ErrorAction SilentlyContinue
    Remove-Variable -Name "supabaseKey" -ErrorAction SilentlyContinue
    Remove-Variable -Name "groqApiKey" -ErrorAction SilentlyContinue
    Remove-Variable -Name "telegramToken" -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "📦 Pulling Docker images..." -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan

# List of Docker images to pull
$images = @(
    "ghcr.io/astral-sh/uv:latest",
    "node:20-alpine",
    "nginx:alpine",
    "postgres:13",
    "redis:7-alpine",
    "coreos/etcd:v3.5.5",
    "minio/minio:RELEASE.2023-03-20T20-16-18Z",
    "milvusdb/milvus:v2.4.9",
    "neo4j:5.15",
    "apache/airflow:2.8.0-python3.10",
    "mcr.microsoft.com/playwright/python:v1.40.0-jammy",
    "prom/prometheus:latest",
    "grafana/grafana:10.2.2",
    "google/cadvisor:latest",
    "prom/node-exporter:latest"
)

# Pull each image
foreach ($image in $images) {
    Write-Host "🔄 Pulling ${image}..." -ForegroundColor Yellow
    try {
        & scripts/pull_image.ps1 $image
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Successfully pulled ${image}" -ForegroundColor Green
        } else {
            Write-Host "❌ Failed to pull ${image}" -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "❌ Error pulling ${image}: $_" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "🎉 Initialization complete!" -ForegroundColor Green
Write-Host "==========================" -ForegroundColor Green
Write-Host "You can now run: docker compose up -d --build" -ForegroundColor Cyan
Write-Host "To include optional stacks, run:" -ForegroundColor Cyan
Write-Host "  docker compose --profile etl up -d" -ForegroundColor Gray
Write-Host "  docker compose --profile monitoring up -d" -ForegroundColor Gray
