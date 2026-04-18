"""
Base interface and exception definitions for document processors.

This module defines a unified document processor interface for OCR and document parsing services.
"""

from abc import ABC, abstractmethod
from typing import Any


class DocumentProcessorException(Exception):
    """Base exception for document processors."""

    def __init__(self, message: str, service_name: str = None, status_code: str = None):
        super().__init__(message)
        self.message = message
        self.service_name = service_name
        self.status_code = status_code

    def __str__(self):
        if self.service_name:
            return f"[{self.service_name}] {self.message}"
        return self.message


class OCRException(DocumentProcessorException):
    """OCR processor exception."""

    pass


class DocumentParserException(DocumentProcessorException):
    """Document parser exception."""

    pass


class ServiceHealthCheckException(DocumentProcessorException):
    """Service health-check exception."""

    pass


class BaseDocumentProcessor(ABC):
    """Base class for document processors."""

    @abstractmethod
    def process_file(self, file_path: str, params: dict[str, Any] | None = None) -> str:
        """
        Process a file and return extracted text.

        Args:
            file_path: File path.
            params: Processing parameters.

        Returns:
            str: Extracted text content.

        Raises:
            DocumentProcessorException: Raised when processing fails.
        """
        pass

    @abstractmethod
    def check_health(self) -> dict[str, Any]:
        """
        Check service health status.

        Returns:
            dict: Health status information.
                {
                    "status": "healthy" | "unhealthy" | "unavailable" | "error",
                    "message": "status description",
                    "details": {...}  # Optional details
                }
        """
        pass

    @abstractmethod
    def get_service_name(self) -> str:
        """Return service name."""
        pass

    def supports_file_type(self, file_extension: str) -> bool:
        """
        Check whether the specified file type is supported.

        Args:
            file_extension: File extension (including dot, e.g. '.pdf').

        Returns:
            bool: Whether it is supported.
        """
        return file_extension.lower() in self.get_supported_extensions()

    @abstractmethod
    def get_supported_extensions(self) -> list[str]:
        """Return the list of supported file extensions."""
        pass
