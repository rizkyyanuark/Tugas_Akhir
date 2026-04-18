import hashlib
import os
import time
import traceback
from pathlib import Path

import aiofiles
from langchain_text_splitters import MarkdownTextSplitter

from yunesa import config
from yunesa.config.static.models import EmbedModelInfo
from yunesa.utils import hashstr, logger
from yunesa.utils.datetime_utils import utc_isoformat


def validate_file_path(file_path: str, db_id: str = None) -> str:
    """
    verifyfilepath，path - fileMinIO URL

    Args:
        file_path: verifyfilepathMinIO URL
        db_id: databaseID，getknowledge baseuploaddirectory

    Returns:
        str: path

    Raises:
        ValueError: path
    """
    try:
        # whetherMinIO URL，return（rowpathcheck）
        if is_minio_url(file_path):
            logger.debug(f"MinIO URL detected, skipping path validation: {file_path}")
            return file_path

        # path（file）
        normalized_path = os.path.abspath(os.path.realpath(file_path))

        # getdirectory
        from yunesa.knowledge import knowledge_base

        allowed_dirs = [
            os.path.abspath(os.path.realpath(config.save_dir)),
        ]

        # db_id，addknowledge baseuploaddirectory
        if db_id:
            try:
                allowed_dirs.append(os.path.abspath(os.path.realpath(knowledge_base.get_db_upload_path(db_id))))
            except Exception:
                # getdbpath，uploaddirectory
                allowed_dirs.append(
                    os.path.abspath(os.path.realpath(os.path.join(config.save_dir, "database", "uploads")))
                )

        # checkpathwhetherdirectory
        is_safe = False
        for allowed_dir in allowed_dirs:
            try:
                if normalized_path.startswith(allowed_dir):
                    is_safe = True
                    break
            except Exception:
                continue

        if not is_safe:
            logger.warning(f"Path traversal attempt detected: {file_path} (normalized: {normalized_path})")
            raise ValueError(f"Access denied: Invalid file path: {file_path}")

        return normalized_path

    except Exception as e:
        logger.error(f"Path validation failed for {file_path}: {e}")
        raise ValueError(f"Invalid file path: {file_path}")


def _unescape_separator(separator: str | None) -> str | None:
    """characterconvertcharacter

    : "\\n\\n\\n" -> "\n\n\n"
    """
    if not separator:
        return None

    # processcolumn
    separator = separator.replace("\\n", "\n")
    separator = separator.replace("\\r", "\r")
    separator = separator.replace("\\t", "\t")
    separator = separator.replace("\\\\", "\\")

    return separator


def sanitize_processing_params(params: dict | None) -> dict | None:
    """removetimes，writefiledata。"""
    if not params:
        return None

    sanitized = params.copy()
    sanitized.pop("_preprocessed_map", None)
    sanitized.pop("content_hashes", None)
    return sanitized


def split_text_into_chunks(text: str, file_id: str, filename: str, params: dict = {}) -> list[dict]:
    """
    split， LangChain  MarkdownTextSplitter rowsplit
    """
    chunks = []
    chunk_size = params.get("chunk_size", 1000)
    chunk_overlap = params.get("chunk_overlap", 200)

    # getconvertcharacter
    separator = params.get("qa_separator")
    separator = _unescape_separator(separator)

    # ：configureset use_qa_split=True  separator，default
    use_qa_split = params.get("use_qa_split", False)
    if use_qa_split and not separator:
        separator = "\n\n\n"
        logger.debug("enabled：use_qa_split=True，default \\n\\n\\n")

    #  MarkdownTextSplitter rowsplit
    # MarkdownTextSplitter  Markdown formattitlerowsplit
    text_splitter = MarkdownTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    # set，splitsplitprocess
    if separator:
        # convertformat（row \n）
        separator_display = separator.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        logger.debug(f"enabledsplit，: '{separator_display}'")
        pre_chunks = text.split(separator)
        text_chunks = []
        for pre_chunk in pre_chunks:
            if pre_chunk.strip():
                text_chunks.extend(text_splitter.split_text(pre_chunk))
    else:
        text_chunks = text_splitter.split_text(text)

    # convertformat
    for chunk_index, chunk_content in enumerate(text_chunks):
        if chunk_content.strip():  # 
            chunks.append(
                {
                    "id": f"{file_id}_chunk_{chunk_index}",
                    "content": chunk_content,  # .strip(),
                    "file_id": file_id,
                    "filename": filename,
                    "chunk_index": chunk_index,
                    "source": filename,
                    "chunk_id": f"{file_id}_chunk_{chunk_index}",
                }
            )

    logger.debug(f"Successfully split text into {len(chunks)} chunks using MarkdownTextSplitter")
    return chunks


async def calculate_content_hash(data: bytes | bytearray | str | os.PathLike[str] | Path) -> str:
    """
    calculatefilecontent SHA-256 hash。

    Args:
        data: filecontentdatafilepath

    Returns:
        str: hash
    """
    sha256 = hashlib.sha256()

    if isinstance(data, (bytes, bytearray)):
        sha256.update(data)
        return sha256.hexdigest()

    if isinstance(data, (str, os.PathLike, Path)):
        path = Path(data)
        async with aiofiles.open(path, "rb") as file_handle:
            chunk = await file_handle.read(8192)
            while chunk:
                sha256.update(chunk)
                chunk = await file_handle.read(8192)

        return sha256.hexdigest()

    # execute，
    raise TypeError(f"Unsupported data type for hashing: {type(data)!r}")  # type: ignore[unreachable]


async def prepare_item_metadata(item: str, content_type: str, db_id: str, params: dict | None = None) -> dict:
    """
    preparingfileURLdata - fileMinIOfile

    Args:
        item: filepathMinIO URL
        content_type: contenttype ("file"  "url")
        db_id: databaseID
        params: processparameter，optional
    """
    # checkwhetherprocess ( URL  HTML file)
    if params and "_preprocessed_map" in params and item in params["_preprocessed_map"]:
        pre_info = params["_preprocessed_map"][item]

        # process
        filename = pre_info.get("filename", item)  #  URL

        # filedatabaselimit (512 chars)，partial
        if len(filename) > 500:
            filename_display = filename[:400] + "..." + filename[-90:]
        else:
            filename_display = filename

        file_type = "html"  # convert html type，fileprocess
        item_path = pre_info["path"]  # MinIO path
        content_hash = pre_info["content_hash"]

        #  item(url) generate ID， URL timesadd ID （ time）
        #  hash？， time upload
        file_id = f"file_{hashstr(item + str(time.time()), 6)}"

        metadata = {
            "database_id": db_id,
            "filename": filename_display,
            "path": item_path,
            "file_type": file_type,
            "status": "processing",
            "created_at": utc_isoformat(),
            "file_id": file_id,
            "content_hash": content_hash,
            "parent_id": params.get("parent_id"),
        }

        if params:
            safe_params = sanitize_processing_params(params) or {}
            #  content_type  file，parsefileworkflow（MinIO download -> HTML parse）
            # times URL 
            safe_params["content_type"] = "file"
            safe_params["original_source"] = item  # save URL  JSON ，databaselimit
            metadata["processing_params"] = safe_params

        return metadata

    if content_type == "file":
        # whetherMinIO URLfilepath
        if is_minio_url(item):
            # MinIOfileprocess
            logger.debug(f"Processing MinIO file: {item}")
            # MinIO URLextractfile
            if "?" in item:
                # URLqueryparameter，
                item_clean = item.split("?")[0]
            else:
                item_clean = item

            # getfile（pathpartial）
            filename = item_clean.split("/")[-1]

            # filetime，extractfile
            import re

            timestamp_pattern = r"^(.+)_(\d{13})(\.[^.]+)$"
            match = re.match(timestamp_pattern, filename)
            if match:
                original_filename = match.group(1) + match.group(3)
                # storagefile
                filename_display = original_filename
            else:
                filename_display = filename

            file_type = filename.split(".")[-1].lower() if "." in filename else ""
            item_path = item  # MinIO URLpath

            #  content_hashes get content_hash
            content_hash = None
            if params and "content_hashes" in params and isinstance(params["content_hashes"], dict):
                content_hash = params["content_hashes"].get(item)

            if not content_hash:
                raise ValueError(f"Missing content_hash for file: {item}")

        else:
            # fileprocess
            file_path = Path(item)
            file_type = file_path.suffix.lower().replace(".", "")
            filename = file_path.name
            filename_display = filename
            item_path = os.path.relpath(file_path, Path.cwd())
            content_hash = None
            try:
                if file_path.exists():
                    content_hash = await calculate_content_hash(file_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to calculate content hash for {file_path}: {exc}")

        # generatefileID
        file_id = f"file_{hashstr(str(item_path) + str(time.time()), 6)}"

    elif content_type == "url":
        # URL process
        filename = item  #  URL file
        filename_display = item
        file_type = "url"
        item_path = item
        content_hash = None  # URL  content_hash
        file_id = f"url_{hashstr(item + str(time.time()), 6)}"

    else:
        raise ValueError(f"Unsupported content_type: {content_type}")

    metadata = {
        "database_id": db_id,
        "filename": filename_display,  # file
        "path": item_path,
        "file_type": file_type,
        "status": "processing",
        "created_at": utc_isoformat(),
        "file_id": file_id,
        "content_hash": content_hash,
        "parent_id": params.get("parent_id") if params else None,
    }

    # saveprocessparameterdata
    if params:
        metadata["processing_params"] = sanitize_processing_params(params)

    return metadata


def merge_processing_params(metadata_params: dict | None, request_params: dict | None) -> dict:
    """
    mergeprocessparameter：requestparameter，dataparameter

    Args:
        metadata_params: datasaveparameter
        request_params: requestparameter

    Returns:
        dict: mergeparameter
    """
    merged_params = {}

    # dataparameterdefault
    if metadata_params:
        merged_params.update(metadata_params)

    # requestparameter（）
    if request_params:
        merged_params.update(request_params)

    logger.debug(f"Merged processing params: {metadata_params=}, {request_params=}, {merged_params=}")
    return merged_params


def get_embedding_config(embed_info: dict) -> dict:
    """
    getembeddingmodelconfigure

    Args:
        embed_info: embedding

    Returns:
        dict: embeddingconfigure
    """
    try:
        # configure
        assert isinstance(embed_info, dict), f"embed_info must be a dict, got {type(embed_info)}"
        assert "model_id" in embed_info, f"embed_info must contain 'model_id', got {embed_info}"
        logger.warning(f"Using model_id: {embed_info['model_id']}")
        config_dict = config.embed_model_names[embed_info["model_id"]].model_dump()
        config_dict["api_key"] = os.getenv(config_dict["api_key"]) or config_dict["api_key"]
        return config_dict

    except AssertionError as e:
        logger.error(f"AssertionError in get_embedding_config: {e}, embed_info={embed_info}")

    # check：configure
    try:
        # 1. check embed_info whethervalid
        if not embed_info or ("model" not in embed_info and "name" not in embed_info):
            logger.error(f"Invalid embed_info: {embed_info}, using default embedding model config")
            raise ValueError("Invalid embed_info: must be a non-empty dictionary")

        # 2. checkwhether EmbedModelInfo （）
        if hasattr(embed_info, "name") and isinstance(embed_info, EmbedModelInfo):
            logger.debug(f"Using EmbedModelInfo object: {embed_info.name}, {traceback.format_exc()}")
            config_dict = embed_info.model_dump()
            config_dict["api_key"] = os.getenv(config_dict["api_key"]) or config_dict["api_key"]
            return config_dict

        raise ValueError(f"Unsupported embed_info format: {embed_info}")

    except Exception as e:
        logger.error(f"Error in get_embedding_config: {e}, embed_info={embed_info}")
        # returndefaultconfigurefallback
        logger.warning("Falling back to default embedding model config")
        try:
            config_dict = config.embed_model_names[config.embed_model].model_dump()
            config_dict["api_key"] = os.getenv(config_dict["api_key"]) or config_dict["api_key"]
            return config_dict
        except Exception as fallback_error:
            logger.error(f"Failed to get default embedding config: {fallback_error}")
            raise ValueError(f"Failed to get embedding config and fallback failed: {e}")


def is_minio_url(file_path: str) -> bool:
    """
    whetherMinIO URL

    Args:
        file_path: filepathURL

    Returns:
        bool: whetherMinIO URL
    """
    return file_path.startswith(("http://", "https://", "s3://")) or "minio" in file_path.lower()


def parse_minio_url(file_path: str) -> tuple[str, str]:
    """
    parseMinIO URL，extractbucketnamename

     HTTP/HTTPS URL format：
    - http(s)://host/bucket-name/path/to/object

    Args:
        file_path: MinIOfileURL (http://  https://)

    Returns:
        tuple[str, str]: (bucket_name, object_name)

    Raises:
        ValueError: parseURL
    """
    try:
        from urllib.parse import urlparse

        # parseURL
        parsed_url = urlparse(file_path)

        #  minio:// ，bucketnamenetloc
        if parsed_url.scheme == "minio":
            bucket_name = parsed_url.netloc
            object_name = parsed_url.path.lstrip("/")
        else:
            #  http/https ，bucketnamepathpartial
            object_name = parsed_url.path.lstrip("/")
            path_parts = object_name.split("/", 1)
            if len(path_parts) > 1:
                bucket_name = path_parts[0]
                object_name = path_parts[1]
            else:
                raise ValueError(f"parseMinIO URLbucketname: {file_path}")

        logger.debug(f"Parsed MinIO URL: bucket_name={bucket_name}, object_name={object_name}")
        return bucket_name, object_name

    except Exception as e:
        logger.error(f"Failed to parse MinIO URL {file_path}: {e}")
        raise ValueError(f"parseMinIO URL: {file_path}")
