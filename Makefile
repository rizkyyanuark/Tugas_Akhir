# ==============================================================================
# 🚀 UNESA Knowledge Graph - Makefile
# ==============================================================================
# Shortcut commands for development and deployment.
# Usage: make <command>
# ==============================================================================

COMPOSE_DEV  = docker compose -p tugas_akhir -f infra/docker/docker-compose.yml --env-file .env
COMPOSE_PROD = docker compose -p tugas_akhir -f infra/docker/docker-compose.prod.yml --env-file .env

# --- Development ---
.PHONY: dev dev-all down logs ps

dev: ## Start core services (Airflow + Neo4j)
	$(COMPOSE_DEV) up -d

dev-vectordb: ## Start with Vector DB (Weaviate)
	$(COMPOSE_DEV) --profile vectordb up -d

dev-monitoring: ## Start with Monitoring (Grafana + Prometheus)
	$(COMPOSE_DEV) --profile monitoring up -d

dev-all: ## Start ALL profiles (core + vectordb + monitoring)
	$(COMPOSE_DEV) --profile vectordb --profile monitoring up -d

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
