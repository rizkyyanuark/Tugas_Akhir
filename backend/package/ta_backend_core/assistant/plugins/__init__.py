# 新的统一文档处理器接口
from ta_backend_core.assistant.plugins.parser.base import (
    BaseDocumentProcessor,
    DocumentParserException,
    DocumentProcessorException,
    OCRException,
)
from ta_backend_core.assistant.plugins.parser.factory import DocumentProcessorFactory

__all__ = [
    "BaseDocumentProcessor",
    "DocumentProcessorException",
    "DocumentParserException",
    "OCRException",
    "DocumentProcessorFactory",  # 推荐使用
]
