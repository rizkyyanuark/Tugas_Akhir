# ==============================================================================
# 🚀 UNESA Knowledge Graph - Makefile
# ==============================================================================
# Shortcut commands for development and deployment.
# Usage: make <command>
# ==============================================================================

COMPOSE_DEV  = docker compose -p tugas_akhir -f docker-compose.yml --env-file .env
COMPOSE_PROD = docker compose -p tugas_akhir -f docker-compose.yml -f docker-compose.prod.yml --env-file .env

# --- Development ---
.PHONY: dev dev-all down logs ps

dev: ## Start core services (API + Web + DBs)
	$(COMPOSE_DEV) up -d --build

dev-etl: ## Start with ETL Profile (Airflow)
	$(COMPOSE_DEV) --profile etl up -d --build

dev-monitoring: ## Start with Monitoring (Grafana + Prometheus)
	$(COMPOSE_DEV) --profile monitoring up -d --build

dev-all: ## Start ALL profiles
	$(COMPOSE_DEV) --profile etl --profile monitoring up -d --build

down: ## Stop all services
	$(COMPOSE_DEV) down

logs: ## Follow logs of all running services
	$(COMPOSE_DEV) logs -f

ps: ## Show running containers
	$(COMPOSE_DEV) ps

# --- Production ---
.PHONY: prod prod-down

prod: ## Start production stack with monitoring
	$(COMPOSE_PROD) --profile monitoring up -d

prod-down: ## Stop production stack
	$(COMPOSE_PROD) down

# --- Deployment ---
.PHONY: deploy push-github push-gitlab

deploy: ## Push to both GitHub and GitLab (triggers CI/CD)
	git push origin main
	git push gitlab main

push-github: ## Push to GitHub only
	git push origin main

push-gitlab: ## Push to GitLab only (triggers CI/CD deploy)
	git push gitlab main

# --- Utilities ---
.PHONY: status help

status: ## Check GitLab pipeline status
	glab ci status --branch main

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
