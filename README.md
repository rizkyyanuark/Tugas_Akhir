<div align="center">

# 🎓 UNESA Knowledge Graph (Project Suncatcher)

**Academic Knowledge Graph Construction & Hybrid GraphRAG Pipeline**

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://python.org)
[![Airflow](https://img.shields.io/badge/Apache%20Airflow-2.8.0-017CEE.svg)](https://airflow.apache.org)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.15-008CC1.svg)](https://neo4j.com)
[![Vue](https://img.shields.io/badge/Vue.js-3.0-4FC08D.svg)](https://vuejs.org/)

*Arsitektur Hybrid: ETL Pipeline (Airflow + Ops) dengan Lapisan Agent & UI untuk eksplorasi Knowledge Graph akademik INFOKOM UNESA.*

</div>

---

## 📋 Daftar Isi

- [Ringkasan Proyek](#ringkasan-proyek)
- [Prinsip Arsitektur (Hybrid Adoption)](#prinsip-arsitektur-hybrid-adoption)
- [Tech Stack](#tech-stack)
- [Struktur Direktori](#struktur-direktori)
- [Cara Menjalankan (Development)](#cara-menjalankan-development)
- [Deployment (CI/CD)](#deployment-cicd)
- [Observability](#observability)

## Ringkasan Proyek

Project **Strwythura** berfokus pada pembangunan _Knowledge Graph_ akademik UNESA dengan pendekatan GraphRAG. Alih-alih menggunakan solusi Black-Box, proyek ini mempertahankan **kedaulatan data (Data Sovereignty)** di layer *Ingestion* (Airflow & Entity Resolution kustom), namun mengintegrasikan framework UI/Agent berbasis **Yuxi** di layer presentasi.

## Prinsip Arsitektur (Hybrid Adoption)

Berdasarkan arahan manajerial, proyek ini menerapkan pemisahan tugas (*separation of concerns*) yang sangat ketat:

1. **Layer Ingestion & ETL (Kustom / Internal)**
   - Proses ekstraksi data akademik, *entity resolution*, dan konstruksi ke Neo4j tetap dikendalikan 100% oleh skrip internal menggunakan Apache Airflow (`/orchestration`).
   - Tidak menggunakan parser dokumen default pihak ketiga untuk menjaga akurasi domain spesifik.

2. **Layer Storage (Neo4j, Milvus, Supabase)**
   - **Supabase (PostgreSQL):** Sebagai Data Warehouse *real-time* untuk tabel dosen & paper.
   - **Neo4j:** Sebagai *System of Record* untuk graf relasional.
   - **Milvus:** Sebagai Vector Database terdedikasi untuk GraphRAG.

3. **Layer Agent & UI (Adopsi Partial dari Yuxi)**
   - Menggunakan referensi *application shell* dari Yuxi untuk fitur Chat UI, Tool Orchestration, dan Agent Workflow (`/web` dan `/backend/server`).
   - Penambahan rute `/dashboard` kustom yang terhubung langsung dengan Supabase & Neo4j untuk visualisasi statistik (Total Paper, Total Dosen) langsung pada UI.

## Tech Stack

| Layer | Teknologi Utama | Peran |
|-------|-----------------|-------|
| **Frontend/UI** | Vue 3, Vite | Chat UI, Node Explorer, Dashboard Akademik |
| **Backend/Agent** | FastAPI, LangGraph | *Query routing*, *Tool orchestration*, *Graph traversal* |
| **Orchestration** | Apache Airflow 2.8.0 | *Job mapping*, *Retry orchestration*, ETL eksternal |
| **Graph DB** | Neo4j 5.15 | *Knowledge Graph Storage* & *Cypher queries* |
| **Vector DB** | Milvus | *Semantic similarity search*, integrasi LlamaIndex |
| **Relational DB**| Supabase, Redis | Tabel faktual, antrean *cache* memori sementara |

## Struktur Direktori

Arsitektur berada pada hirarki *root-level* untuk memfasilitasi _microservices_ secara mandiri.

```text
Tugas_Akhir/
├── README.md                      # Dokumentasi ini
├── Makefile                       # Pintasan perintah sistem (make dev-all, make clean)
├── .env                           # Credential & Routing (Critical Mismatches terpecahkan)
├── docker-compose.yml             # Orkestrasi container root level
├── docker-compose.prod.yml        # Override produksi untuk deployment
│
├── web/                           # 🟢 Frontend Application (Vite/Vue3)
│   ├── src/views/DashboardView.vue# Ekstensi Kustom: Statistik Akademik
│   └── (Yuxi Application Shell)
│
├── backend/                       # 🟢 Agent & API Service
│   ├── server/routers/            # API Endpoints (termasuk /stats/academic)
│   └── package/ta_backend_core/   # LangGraph Agents, Tools & Config (info.local.yaml)
│
├── orchestration/                 # 🟢 Airflow Pipeline & Scripts
│   ├── dags/                      # Definisi Pipeline (unesa_papers_dag.py dsb)
│   └── (Skrip Scraper Internal)
│
├── docker/                        # 🟢 Container Definitions
│   ├── api.Dockerfile             # Image untuk backend FastAPI
│   ├── web.Dockerfile             # Image untuk frontend Vue
│   ├── airflow.Dockerfile         # Image khusus Airflow + Dependencies
│   └── etl-worker.Dockerfile      # Image independen eksekusi Scraping
│
├── configs/                       # Konfigurasi Milvus, Redis, Database
├── monitoring/                    # Grafana & Prometheus (Akan Difokuskan di Fase 3)
└── scripts/                       # Shell scripts (setup EC2, dsb)
```

## Cara Menjalankan (Development)

Sistem menggunakan Docker Compose tunggal. Direkomendasikan menggunakan instance minimum **8GB RAM** untuk dapat mengangkat seluruh *stack* Graph + Vector + LLM Agent.

### Persiapan

```bash
# 1. Clone repository
git clone https://github.com/rizkyyanuark/Tugas_Akhir.git
cd Tugas_Akhir

# 2. Siapkan Environment (Cek .env)
# Pastikan YUXI_BRAND_FILE_PATH, SUPABASE_URL, NEO4J_URI terisi.
```

### Memulai Aplikasi Lengkap (API, Web, Neo4j, Milvus, Redis)
Hanya menjalankan aplikasi inti (*End-User Layer*).

```bash
docker compose up -d postgres graph redis milvus etcd minio api web
```

### Memulai Mode ETL & Scraping Terpisah
Jalankan ini ketika hanya ingin memproses Airflow atau membangun Graph tanpa menyalakan UI.

```bash
docker compose --profile etl up -d
```

Atau gunakan file `Makefile` yang telah disediakan.

## Deployment (CI/CD)

Proyek ini telah dikonfigurasi melalui `.gitlab-ci.yml`. Setiap *push* ke `main` branch akan:
1. Melakukan kompilasi *images* `API`, `Web`, `Airflow`, dan `Worker` ke AWS ECR.
2. Membuka koneksi `SSH` menujuu Instans AWS EC2.
3. Melakukan sinkronisasi direktori root melalui `scp`.
4. Mengeksekusi ulang `docker compose` di server AWS dengan modifikasi `.prod.yml`.

> **Status Saat Ini:** Deploy sukses. Pipeline terintegrasi mulus.

## Observability

Sistem dilengkapi dengan:
- **Opik / Langfuse:** Untuk melacak *Agent Trace* (Input/Output LLM, *Tool Calling Time*).
- **Langkah Kedepan (Fase 3):** Implementasi Grafana Cloud atau setup Prometheus lokal untuk memonitor beban *RAM Milvus* dan *Neo4j IOPS*.

---
<div align="center">
  <b>Rizky Yanuar Kristianto</b> — Sains Data, Universitas Negeri Surabaya (UNESA) <br>
  <i>Knowledge Graph RAG Pipeline 2025/2026</i>
</div>
