import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import logging

# Ensure project root is in path
ROOT_DIR = str(Path(os.getcwd()))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)

# Load .env variables (including 127.0.0.1 for WEAVIATE_HOST)
load_dotenv(override=True)

# Setup basic logging
logging.basicConfig(level=logging.INFO)

print("==== Weaviate ENV Check ====")
print("WEAVIATE_HOST:", os.environ.get("WEAVIATE_HOST"))
print("WEAVIATE_PORT:", os.environ.get("WEAVIATE_PORT"))
print("============================")

from src.kg.services.kg_pipeline import KGPipeline

print("\n🚀 Initializing KGPipeline (Test Mode)...")
try:
    pipeline = KGPipeline(test_mode=True, clear_db=True)
    print("\n🚀 Starting Pipeline Ingestion...")
    pipeline.ingest_databases()
    print("\n✅ Ingestion Test Completed Successfully!")
except Exception as e:
    print("\n❌ Pipeline Ingestion Failed:")
    import traceback
    traceback.print_exc()
