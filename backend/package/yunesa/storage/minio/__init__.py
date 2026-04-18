"""
MinIO storage module
Simplified object storage features
"""

# Export core functionality
from .client import MinIOClient, StorageError, UploadResult, aupload_file_to_minio, get_minio_client
from .utils import generate_unique_filename, get_file_size

# Export common functions for backward compatibility
__all__ = [
    # Core functionality
    "MinIOClient",
    "get_minio_client",
    "aupload_file_to_minio",
    # Exception classes
    "StorageError",
    "UploadResult",
    # Utility functions
    "get_file_size",
    "generate_unique_filename",
]
