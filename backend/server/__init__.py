# ══════════════════════════════════════════════════════════════
# src/backend — KG Construction FastAPI Backend
# ══════════════════════════════════════════════════════════════
# Event-driven backend that receives webhook triggers from
# Airflow ETL, pulls data from Supabase, runs NLP extraction
# (GLiNER + SpaCy), and persists to Neo4j + Weaviate.
#
# Deployment: Separate EC2 instance (Server B)
# Framework: FastAPI + Uvicorn
# ══════════════════════════════════════════════════════════════

__version__ = "0.1.0"
