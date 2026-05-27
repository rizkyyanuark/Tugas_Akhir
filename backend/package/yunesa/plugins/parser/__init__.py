from yunesa.plugins.parser.base import (
    BaseDocumentProcessor,
    DocumentParserException,
    DocumentProcessorException,
    OCRException,
)
from yunesa.plugins.parser.factory import DocumentProcessorFactory


_UNIFIED_EXPORTS = {
    "SUPPORTED_FILE_EXTENSIONS",
    "MarkdownParseResult",
    "Parser",
    "is_supported_file_extension",
    "parse_source_to_markdown",
}


def __getattr__(name: str):
    if name in _UNIFIED_EXPORTS:
        from importlib import import_module

        unified = import_module("yunesa.plugins.parser.unified")
        value = getattr(unified, name)
        globals()[name] = value
        return value
    raise AttributeError(name)

__all__ = [
    "BaseDocumentProcessor",
    "DocumentProcessorException",
    "DocumentParserException",
    "OCRException",
    "DocumentProcessorFactory",
    "MarkdownParseResult",
    "Parser",
    "SUPPORTED_FILE_EXTENSIONS",
    "is_supported_file_extension",
    "parse_source_to_markdown",
]
