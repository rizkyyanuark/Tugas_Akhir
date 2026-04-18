import os

from ..config import config
from .factory import KnowledgeBaseFactory
from .implementations.dify import DifyKB
from .manager import KnowledgeBaseManager

_LITE_MODE = os.environ.get("LITE_MODE", "").lower() in ("true", "1")
_SKIP_APP_INIT = os.environ.get("YUNESA_SKIP_APP_INIT") == "1"

if not _LITE_MODE:
    from .graphs.upload_graph_service import UploadGraphService
    from .implementations.lightrag import LightRagKB
    from .implementations.milvus import MilvusKB

    # Register knowledge base types
    KnowledgeBaseFactory.register(
        "milvus", MilvusKB, {
            "description": "Production-grade vector knowledge base based on Milvus for high-performance deployment"}
    )
    KnowledgeBaseFactory.register(
        "lightrag", LightRagKB, {
            "description": "Graph-based knowledge base supporting entity relationship construction and complex queries"}
    )

KnowledgeBaseFactory.register("dify", DifyKB, {
                              "description": "Read-only retrieval knowledge base connected to Dify Dataset"})

# Create knowledge base manager
work_dir = os.path.join(config.save_dir, "knowledge_base_data")
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
    # Backward compatibility
    GraphDatabase = _LiteGraphStub
    if _LITE_MODE:
        logger.info("LITE_MODE enabled, knowledge graph services disabled")
    else:
        logger.info(
            "YUNESA_SKIP_APP_INIT enabled, knowledge graph services disabled for current process")
else:
    graph_base = UploadGraphService()
    # Backward compatibility: make GraphDatabase point to UploadGraphService
    GraphDatabase = UploadGraphService

__all__ = ["GraphDatabase", "knowledge_base", "graph_base"]
