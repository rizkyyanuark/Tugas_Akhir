# ══════════════════════════════════════════════════════════════
# src/kg — Knowledge Graph Construction Module
# ══════════════════════════════════════════════════════════════
# Production-ready KG construction pipeline for UNESA academic
# literature. Extracts entities from paper TLDRs using GLiNER,
# resolves duplicates via 3-layer entity resolution, curates
# with Groq LLM, and persists to Neo4j + Milvus.
#
# Usage (from notebook):
#   from ta_backend_core.knowledge.kg.services.kg_pipeline import KGPipeline
#   pipeline = KGPipeline(test_mode=True)
#   pipeline.run()
#
# Usage (from Airflow):
#   from ta_backend_core.knowledge.kg.services.kg_pipeline import run_full_pipeline
#   run_full_pipeline()
# ══════════════════════════════════════════════════════════════

__version__ = "0.1.0"
