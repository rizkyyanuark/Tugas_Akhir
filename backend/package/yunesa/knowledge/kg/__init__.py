# ══════════════════════════════════════════════════════════════
# yunesa.knowledge.kg — Knowledge Graph Construction Module
# ══════════════════════════════════════════════════════════════
# Production-ready KG construction pipeline for UNESA academic
# literature. Extracts entities from paper TLDRs using GLiNER,
# resolves duplicates via 3-layer entity resolution, curates
# with Groq LLM, and persists to Neo4j + Milvus.
#
# Usage (from backend API — superadmin only):
#   POST /api/knowledge/kg/build
#
# Usage (programmatic):
#   from yunesa.knowledge.kg.services.kg_pipeline import KGPipeline
#   pipeline = KGPipeline(test_mode=True)
#   pipeline.run()
# ══════════════════════════════════════════════════════════════

__version__ = "0.2.0"
