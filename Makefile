# ==============================================================================
# Yunesa Knowledge Graph - Makefile
# ==============================================================================
# Shortcut commands for development and deployment.
# Usage: make <command>
# ==============================================================================

COMPOSE_DEV  = docker compose -p tugas_akhir -f docker-compose.yml --env-file .env
COMPOSE_PROD = docker compose -p tugas_akhir -f docker-compose.prod.yml --env-file .env

# --- Development ---
.PHONY: dev dev-etl dev-monitoring dev-all down logs ps

dev: ## Start core development services
	$(COMPOSE_DEV) up -d --build

dev-etl: ## Start development services with ETL and Airflow
	$(COMPOSE_DEV) --profile etl up -d --build

dev-monitoring: ## Start development services with monitoring
	$(COMPOSE_DEV) --profile monitoring up -d --build

dev-all: ## Start all development profiles
	$(COMPOSE_DEV) --profile etl --profile monitoring up -d --build

down: ## Stop development services
	$(COMPOSE_DEV) down

logs: ## Follow development service logs
	$(COMPOSE_DEV) logs -f

ps: ## Show development service status
	$(COMPOSE_DEV) ps

# --- Production ---
.PHONY: prod prod-down

prod: ## Start production services with ETL and Cloudflare Tunnel
	$(COMPOSE_PROD) --profile etl up -d --build

prod-down: ## Stop production services
	$(COMPOSE_PROD) --profile etl down

# --- Deployment ---
.PHONY: deploy push-dev push-master

deploy: ## Push release-ready master and trigger production deployment
	git push origin master

push-dev: ## Push development branch without production deployment
	git push origin dev

push-master: ## Push master branch to GitHub
	git push origin master

# --- Utilities ---
.PHONY: etl-new status help

etl-new: ## Create a new ETL pipeline module and DAG
	python scripts/new_etl_pipeline.py --pipeline "$(PIPELINE)" $(EXTRA_ARGS)

status: ## Show recent production deployment runs
	gh run list --workflow deploy.yml --branch master --limit 5

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
