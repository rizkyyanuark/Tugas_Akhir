import os
from yunesa import config as global_config
from .factory import KnowledgeBaseFactory
from .manager import KnowledgeBaseManager

_LITE_MODE = os.environ.get("LITE_MODE", "").lower() in ("true", "1")
_SKIP_APP_INIT = os.environ.get("YUNESA_SKIP_APP_INIT") == "1"

if not _LITE_MODE:
    from .graphs.core_graph_service import CoreGraphService
    from .implementations.milvus import MilvusKB, AcademicKGVectorStore

    # Register knowledge base types
    KnowledgeBaseFactory.register(
        "milvus", MilvusKB, {
            "description": "Production-grade vector knowledge base based on Milvus for UNESA Academic Knowledge Graph deployment"}
    )

# Create knowledge base manager
work_dir = os.path.join(global_config.save_dir, "knowledge_base_data")
knowledge_base = KnowledgeBaseManager(work_dir)

# Create graph database instance
if _LITE_MODE or _SKIP_APP_INIT:
    from ..utils import logger

    class _LiteGraphStub:
        """Graph database placeholder in Lite mode; all operations report unavailable."""

        def is_running(self):
            return False

        def get_graph_info(self, *args, **kwargs):
            return None

    graph_base = _LiteGraphStub()
    GraphDatabase = _LiteGraphStub
    if _LITE_MODE:
        logger.info("LITE_MODE enabled, knowledge graph services disabled")
    else:
        logger.info(
            "YUNESA_SKIP_APP_INIT enabled, knowledge graph services disabled for current process")
else:
    class _LazyGraphBaseProxy:
        """Lazy proxy for CoreGraphService to avoid network calls on module import."""

        def __init__(self):
            self._service = None

        def _get_service(self):
            if self._service is None:
                self._service = CoreGraphService()
            return self._service

        def __getattr__(self, name):
            return getattr(self._get_service(), name)

    graph_base = _LazyGraphBaseProxy()
    GraphDatabase = CoreGraphService

from .graphs.builder import AcademicKGBuilder
from .config import KGConfig
from .services.kg_service import run_kg_build
from .graphs.storage_neo4j import write_graph_to_neo4j
from .implementations.milvus import write_vector_index_to_milvus, AcademicKGVectorStore

__all__ = [
    "GraphDatabase",
    "knowledge_base",
    "graph_base",
    "AcademicKGBuilder",
    "AcademicKGVectorStore",
    "KGConfig",
    "run_kg_build",
    "write_graph_to_neo4j",
    "write_vector_index_to_milvus",
]
