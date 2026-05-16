from __future__ import annotations

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, Any

import fsspec
import pandas as pd

logger = logging.getLogger(__name__)


def normalize_storage_path(path: Union[str, Path]) -> str:
    """
    Normalize storage paths without passing URI schemes through pathlib.

    pathlib turns `s3://bucket/key` into `s3:/bucket/key`; this helper repairs
    that legacy shape and keeps remote URIs as plain strings.
    """
    path_str = str(path)
    if path_str.startswith("s3:/") and not path_str.startswith("s3://"):
        return "s3://" + path_str[len("s3:/"):].lstrip("/")
    return path_str


def is_remote_path(path: Union[str, Path]) -> bool:
    return normalize_storage_path(path).startswith("s3://")

def get_filesystem(path: Union[str, Path]) -> fsspec.AbstractFileSystem:
    """
    Returns the appropriate fsspec filesystem for a given path.
    Supports local files and S3.
    """
    path_str = normalize_storage_path(path)
    if path_str.startswith("s3://"):
        client_kwargs: dict[str, str] = {}
        endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        return fsspec.filesystem(
            "s3",
            key=os.environ.get("AWS_ACCESS_KEY_ID"),
            secret=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            client_kwargs=client_kwargs,
        )
    return fsspec.filesystem("file")

def path_exists(path: Union[str, Path]) -> bool:
    """
    Checks if a file or directory exists on the local filesystem or S3.
    """
    if not path:
        return False
    fs = get_filesystem(path)
    return fs.exists(normalize_storage_path(path))

def delete_file(path: Union[str, Path]) -> None:
    """
    Removes a file from the local filesystem or S3.
    """
    if not path:
        return
    fs = get_filesystem(path)
    path_str = normalize_storage_path(path)
    if fs.exists(path_str):
        fs.rm(path_str)
        logger.info(f"Deleted file: {path_str}")

def get_modification_time(path: Union[str, Path]) -> Optional[datetime]:
    """
    Retrieves the last modified time of a file as a datetime object.
    Works for both local and S3 storage.
    """
    if not path:
        return None
    
    fs = get_filesystem(path)
    path_str = normalize_storage_path(path)
    
    if not fs.exists(path_str):
        return None
    
    # fsspec info returns a dict with 'mtime' (unix timestamp) or 'LastModified' (datetime)
    info = fs.info(path_str)
    mtime = info.get('mtime') or info.get('LastModified')
    
    if isinstance(mtime, (int, float)):
        return datetime.fromtimestamp(mtime)
    return mtime # Already a datetime object

def build_path(base_dir: Union[str, Path], filename: str) -> Union[str, Path]:
    """
    Helper to combine a base directory with a filename, correctly handling S3 URIs.
    """
    base_str = str(base_dir).rstrip("/")
    if base_str.startswith("s3://"):
        return f"{base_str}/{filename}"
    return Path(base_str) / filename


def ensure_parent_dir(path: Union[str, Path]) -> None:
    """Create local parent directories. Remote object stores do not need this."""
    if is_remote_path(path):
        return
    Path(normalize_storage_path(path)).parent.mkdir(parents=True, exist_ok=True)


def write_dataframe_csv(df: pd.DataFrame, path: Union[str, Path], **kwargs: Any) -> None:
    """Write a DataFrame to local disk or S3 without corrupting URI schemes."""
    path_str = normalize_storage_path(path)
    if is_remote_path(path_str):
        fs = get_filesystem(path_str)
        with fs.open(path_str, "w") as handle:
            df.to_csv(handle, **kwargs)
        return

    ensure_parent_dir(path_str)
    df.to_csv(path_str, **kwargs)


def read_dataframe_csv(path: Union[str, Path], **kwargs: Any) -> pd.DataFrame:
    """Read a CSV from local disk or S3 without passing remote URIs to pathlib."""
    path_str = normalize_storage_path(path)
    if is_remote_path(path_str):
        fs = get_filesystem(path_str)
        with fs.open(path_str, "rb") as handle:
            return pd.read_csv(handle, **kwargs)
    return pd.read_csv(path_str, **kwargs)


def get_path_obj(base_dir: Union[str, Path], filename: str) -> Union[str, Path]:
    """Backward-compatible alias for build_path()."""
    return build_path(base_dir, filename)


def smart_exists(path: Union[str, Path]) -> bool:
    """Backward-compatible alias for path_exists()."""
    return path_exists(path)


def smart_unlink(path: Union[str, Path]) -> None:
    """Backward-compatible alias for delete_file()."""
    delete_file(path)


def path_name(path: Union[str, Path]) -> str:
    """Return a display filename for local paths and URI-like paths."""
    if hasattr(path, "name"):
        return path.name
    return normalize_storage_path(path).rstrip("/").split("/")[-1]
