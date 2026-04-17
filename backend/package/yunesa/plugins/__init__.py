# 新的统一文档处理器接口
from yunesa.plugins.parser.base import (
    BaseDocumentProcessor,
    DocumentParserException,
    DocumentProcessorException,
    OCRException,
)
from yunesa.plugins.parser.factory import DocumentProcessorFactory

__all__ = [
    "BaseDocumentProcessor",
    "DocumentProcessorException",
    "DocumentParserException",
    "OCRException",
    "DocumentProcessorFactory",  # 推荐使用
]
