"""
Document processor factory.

Provides a unified interface for creating and managing document processors.
"""

import asyncio
from importlib import import_module
from typing import Any

from yunesa.plugins.parser.base import BaseDocumentProcessor
from yunesa.utils import logger

# Processor instance cache
_PROCESSOR_CACHE: dict[str, BaseDocumentProcessor] = {}


class DocumentProcessorFactory:
    """Document processor factory."""

    # Processor type mapping: processor_type -> (module_path, class_name)
    PROCESSOR_TYPES = {
        "rapid_ocr": ("yunesa.plugins.parser.rapid_ocr", "RapidOCRParser"),
        "mineru_ocr": ("yunesa.plugins.parser.mineru", "MinerUParser"),
        "mineru_official": ("yunesa.plugins.parser.mineru_official", "MinerUOfficialParser"),
        "pp_structure_v3_ocr": ("yunesa.plugins.parser.pp_structure_v3", "PPStructureV3Parser"),
        "deepseek_ocr": ("yunesa.plugins.parser.deepseek_ocr", "DeepSeekOCRParser"),
    }

    @classmethod
    def _build_cache_key(cls, processor_type: str, kwargs: dict[str, Any]) -> str:
        if not kwargs:
            return processor_type

        kwargs_repr = "|".join(
            f"{key}={kwargs[key]!r}" for key in sorted(kwargs))
        return f"{processor_type}|{kwargs_repr}"

    @classmethod
    def _load_processor_class(cls, processor_type: str) -> type[BaseDocumentProcessor]:
        module_path, class_name = cls.PROCESSOR_TYPES[processor_type]
        module = import_module(module_path)
        processor_class = getattr(module, class_name)
        return processor_class

    @classmethod
    def get_processor(cls, processor_type: str, **kwargs) -> BaseDocumentProcessor:
        """
        Get a document processor instance (singleton style).

        Args:
            processor_type: Processor type
                - "rapid_ocr": RapidOCR local OCR
                - "mineru_ocr": MinerU HTTP API document parsing
                - "mineru_official": MinerU official cloud API document parsing
                - "pp_structure_v3_ocr": PP-Structure-V3 layout parsing
                - "deepseek_ocr": DeepSeek-OCR SiliconFlow API
            **kwargs: Processor initialization parameters

        Returns:
            BaseDocumentProcessor: Processor instance

        Raises:
            ValueError: Unsupported processor type
        """
        if processor_type not in cls.PROCESSOR_TYPES:
            raise ValueError(
                f"Unsupported processor type: {processor_type}. Supported types: {list(cls.PROCESSOR_TYPES.keys())}")

        # Use cache to avoid duplicate creation
        cache_key = cls._build_cache_key(processor_type, kwargs)
        if cache_key not in _PROCESSOR_CACHE:
            processor_class = cls._load_processor_class(processor_type)
            _PROCESSOR_CACHE[cache_key] = processor_class(**kwargs)
            logger.debug(f"Created document processor: {processor_type}")

        return _PROCESSOR_CACHE[cache_key]

    @classmethod
    def process_file(cls, processor_type: str, file_path: str, params: dict | None = None) -> str:
        """
        Process file with specified processor (convenience method).

        Args:
            processor_type: Processor type
            file_path: File path
            params: Processing parameters

        Returns:
            str: Extracted text

        Raises:
            DocumentProcessorException: Processing failed
        """
        processor = cls.get_processor(processor_type)
        return processor.process_file(file_path, params)

    @classmethod
    def check_health(cls, processor_type: str) -> dict[str, Any]:
        """
        Check health status of specified processor.

        Args:
            processor_type: Processor type

        Returns:
            dict: Health status information
        """
        try:
            processor = cls.get_processor(processor_type)
            return processor.check_health()
        except Exception as e:
            return {
                "status": "error",
                "message": f"Health check failed: {str(e)}",
                "details": {"error": str(e)},
            }

    @classmethod
    def check_all_health(cls) -> dict[str, dict[str, Any]]:
        """
        Check health status of all processors.

        Returns:
            dict: Health status for each processor
        """
        health_status = {}
        for processor_type in cls.PROCESSOR_TYPES:
            health_status[processor_type] = cls.check_health(processor_type)
        return health_status

    @classmethod
    async def check_all_health_async(cls) -> dict[str, dict[str, Any]]:
        async def run_check(processor_type: str) -> tuple[str, dict[str, Any]]:
            return processor_type, await asyncio.to_thread(cls.check_health, processor_type)

        results = await asyncio.gather(*(run_check(processor_type) for processor_type in cls.PROCESSOR_TYPES))
        return {processor_type: health for processor_type, health in results}

    @classmethod
    def get_available_processors(cls) -> list[str]:
        """Return all available processor types."""
        return list(cls.PROCESSOR_TYPES.keys())

    @classmethod
    def clear_cache(cls):
        """Clear processor cache."""
        _PROCESSOR_CACHE.clear()
        logger.debug("Document processor cache cleared")
