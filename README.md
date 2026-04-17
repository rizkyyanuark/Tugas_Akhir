<div align="center">

# 🎓 UNESA Knowledge Graph (Project Suncatcher)

**Academic Knowledge Graph Construction & Hybrid GraphRAG Pipeline**

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://python.org)
[![Airflow](https://img.shields.io/badge/Apache%20Airflow-2.8.0-017CEE.svg)](https://airflow.apache.org)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.15-008CC1.svg)](https://neo4j.com)
[![Vue](https://img.shields.io/badge/Vue.js-3.0-4FC08D.svg)](https://vuejs.org/)

*Hybrid Architecture: ETL Pipeline (Airflow + Ops) with Agent & UI Layer for explorer of UNESA INFOKOM academic Knowledge Graph.*

</div>

---

## 📋 Table of Contents

- [Project Summary](#project-summary)
- [Architectural Principles (Hybrid Adoption)](#architectural-principles-hybrid-adoption)
- [Tech Stack](#tech-stack)
- [Directory Structure](#directory-structure)
- [How to Run (Development)](#how-to-run-development)
- [Deployment (CI/CD)](#deployment-cicd)
- [Observability](#observability)

## Project Summary

Project **Strwythura** focuses on building an academic Knowledge Graph for UNESA using the GraphRAG approach. Instead of using Black-Box solutions, this project maintains **Data Sovereignty** at the *Ingestion* layer (custom Airflow & Entity Resolution), but integrates a UI/Agent framework based on **agenticrag** at the presentation layer.

## Architectural Principles (Hybrid Adoption)

Based on managerial guidance, this project applies a strict *separation of concerns*:

1. **Ingestion & ETL Layer (Custom / Internal)**
   - The process of academic data extraction, *entity resolution*, and construction into Neo4j remains 100% controlled by internal scripts using Apache Airflow (`/orchestration`).
   - Does not use default third-party document parsers to maintain domain-specific accuracy.

2. **Storage Layer (Neo4j, Milvus, Supabase)**
   - **Supabase (PostgreSQL):** As a *real-time* Data Warehouse for lecturer & paper tables.
   - **Neo4j:** As the *System of Record* for relational graphs.
   - **Milvus:** As a dedicated Vector Database for GraphRAG.

3. **Agent & UI Layer (Partial Adoption from agenticrag)**
   - Uses the *application shell* from agenticrag as reference for Chat UI, Tool Orchestration, and Agent Workflow features (`/web` and `/backend/server`).
   - Addition of custom `/dashboard` routes directly connected to Supabase & Neo4j for statistical visualization (Total Papers, Total Lecturers) directly on the UI.

## Tech Stack

| Layer | Primary Technology | Role |
|-------|-----------------|-------|
| **Frontend/UI** | Vue 3, Vite | Chat UI, Node Explorer, Academic Dashboard |
| **Backend/Agent** | FastAPI, LangGraph | *Query routing*, *Tool orchestration*, *Graph traversal* |
| **Orchestration** | Apache Airflow 2.8.0 | *Job mapping*, *Retry orchestration*, External ETL |
| **Graph DB** | Neo4j 5.15 | *Knowledge Graph Storage* & *Cypher queries* |
| **Vector DB** | Milvus | *Semantic similarity search*, LlamaIndex integration |
| **Relational DB**| Supabase, Redis | Factual tables, temporary memory cache queue |

## Directory Structure

The architecture is at the *root-level* hierarchy to facilitate independent *microservices*.

```text
Tugas_Akhir/
├── README.md                      # This documentation
├── Makefile                       # System command shortcuts (make dev-all, make clean)
├── .env                           # Credentials & Routing (Critical Mismatches solved)
├── docker-compose.yml             # Root-level container orchestration
├── docker-compose.prod.yml        # Production override for deployment
│
├── web/                           # 🟢 Frontend Application (Vite/Vue3)
│   ├── src/views/DashboardView.vue# Custom Extension: Academic Statistics
│   └── (agenticrag Application Shell)
│
├── backend/                       # 🟢 Agent & API Service
│   ├── server/routers/            # API Endpoints (including /stats/academic)
│   └── package/ta_backend_core/   # LangGraph Agents, Tools & Config (info.local.yaml)
│
├── orchestration/                 # 🟢 Airflow Pipeline & Scripts
│   ├── dags/                      # Pipeline Definitions (unesa_papers_dag.py etc.)
│   └── (Internal Scraper Scripts)
│
├── docker/                        # 🟢 Container Definitions
│   ├── api.Dockerfile             # Image for backend FastAPI
│   ├── web.Dockerfile             # Image for frontend Vue
│   ├── airflow.Dockerfile         # Special Airflow Image + Dependencies
│   └── etl-worker.Dockerfile      # Independent Scraping execution image
│
├── configs/                       # Milvus, Redis, Database configurations
├── monitoring/                    # Grafana & Prometheus (Focus in Phase 3)
└── scripts/                       # Shell scripts (EC2 setup, etc.)
```

## How to Run (Development)

The system uses a single Docker Compose. A minimum of **8GB RAM** instance is recommended to lift the entire Graph + Vector + LLM Agent stack.

### Preparation

```bash
# 1. Clone repository
git clone https://github.com/rizkyyanuark/Tugas_Akhir.git
cd Tugas_Akhir

# 2. Prepare Environment (Check .env)
# Ensure AGENTICRAG_BRAND_FILE_PATH, SUPABASE_URL, NEO4J_URI are filled.
```

### Start Full Application (API, Web, Neo4j, Milvus, Redis)
Only starts the core application (*End-User Layer*).

```bash
docker compose up -d postgres graph redis milvus etcd minio api web
```

### Start Separate ETL & Scraping Mode
Run this when you only want to process Airflow or build the Graph without starting the UI.

```bash
docker compose --profile etl up -d
```

Or use the provided `Makefile`.

## Deployment (CI/CD)

This project is configured via `.gitlab-ci.yml`. Each *push* to the `main` branch will:
1. Compile `API`, `Web`, `Airflow`, and `Worker` *images* to AWS ECR.
2. Open an `SSH` connection to the AWS EC2 Instance.
3. Synchronize the root directory via `scp`.
4. Re-execute `docker compose` on the AWS server with `.prod.yml` modification.

> **Current Status:** Deployment successful. Pipeline integration is seamless.

## Observability

The system is equipped with:
- **Opik / Langfuse:** To track *Agent Trace* (LLM Input/Output, *Tool Calling Time*).
- **Future Steps (Phase 3):** Implementation of Grafana Cloud or local Prometheus setup to monitor *Milvus RAM* load and *Neo4j IOPS*.

---
<div align="center">
  <b>Rizky Yanuar Kristianto</b> — Data Science, Surabaya State University (UNESA) <br>
  <i>Knowledge Graph RAG Pipeline 2025/2026</i>
</div>
