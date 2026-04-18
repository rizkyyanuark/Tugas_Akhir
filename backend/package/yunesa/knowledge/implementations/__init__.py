"""knowledge base具体实现模块

包含各种knowledge base的具体实现：
- MilvusKB: 基于 Milvus 的vectorknowledge base
- LightRagKB: 基于 LightRAG 的图retrievalknowledge base
- DifyKB: 基于 Dify retrieval API 的只读knowledge base
"""

from .dify import DifyKB
from .lightrag import LightRagKB
from .milvus import MilvusKB

__all__ = ["MilvusKB", "LightRagKB", "DifyKB"]
