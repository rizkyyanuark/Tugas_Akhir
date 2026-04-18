# New unified document processor interface
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
    "DocumentProcessorFactory",  # Recommended
]
