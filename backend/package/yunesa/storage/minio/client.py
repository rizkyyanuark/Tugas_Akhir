"""
MinIO storageclient
Simplified MinIO object storage operations
"""

import asyncio
import json
import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from io import BytesIO

from urllib3 import BaseHTTPResponse
from yunesa.utils import logger

from minio import Minio
from minio.error import S3Error


class StorageError(Exception):
    """Base class for storage-related exceptions."""

    pass


class StorageUploadError(StorageError):
    """Storage upload exception."""


class UploadResult:
    """Simplified upload result."""

    def __init__(self, url: str, bucket_name: str, object_name: str):
        self.url = url
        self.bucket_name = bucket_name
        self.object_name = object_name


class MinIOClient:
    """
    Simplified MinIO client class.
    """

    PUBLIC_READ_BUCKETS = {"public"}

    # Knowledge base related bucket names
    KB_BUCKETS = {
        "documents": "knowledgebases",
        "parsed": "knowledgebases",
        "images": "public",
    }

    def __init__(self):
        """initialize MinIO client"""
        self.endpoint = os.getenv("MINIO_URI") or "http://minio:9000"
        self.access_key = os.getenv("MINIO_ACCESS_KEY") or "minioadmin"
        self.secret_key = os.getenv("MINIO_SECRET_KEY") or "minioadmin"
        self._client = None

        # Set public access endpoint
        if os.getenv("RUNNING_IN_DOCKER"):
            host_ip = (os.getenv("HOST_IP") or "").strip()
            if not host_ip:
                host_ip = "localhost"
            if "://" in host_ip:
                host_ip = host_ip.split("://")[-1]
            host_ip = host_ip.rstrip("/")
            self.public_endpoint = f"{host_ip}:9000"
            logger.debug(
                f"Docker MinIOClient public_endpoint: {self.public_endpoint}")
        else:
            self.public_endpoint = "localhost:9000"
            logger.debug(f"Default_client: {self.public_endpoint}")

    @property
    def client(self) -> Minio:
        """Get MinIO client instance."""
        if self._client is None:
            endpoint = self.endpoint
            if "://" in endpoint:
                endpoint = endpoint.split("://")[-1]

            self._client = Minio(
                endpoint=endpoint, access_key=self.access_key, secret_key=self.secret_key, secure=False
            )
        return self._client

    def ensure_bucket_exists(self, bucket_name: str) -> bool:
        """Ensure bucket exists."""
        try:
            created = False
            if not self.client.bucket_exists(bucket_name=bucket_name):
                self.client.make_bucket(bucket_name=bucket_name)
                created = True
                logger.info(f"Storage bucket '{bucket_name}' created")

            self._ensure_public_read_access(bucket_name)

            if created and bucket_name in self.PUBLIC_READ_BUCKETS:
                logger.info(
                    f"Storage bucket '{bucket_name}' configured as publicly readable")

            return True
        except S3Error as e:
            logger.error(f"Storage bucket '{bucket_name}' error: {e}")
            raise StorageError(f"Error with bucket '{bucket_name}': {e}")
        except StorageError:
            raise

    def upload_file(
        self, bucket_name: str, object_name: str, data: bytes, content_type: str | None = None
    ) -> UploadResult:
        """Upload file to MinIO."""
        try:
            self.ensure_bucket_exists(bucket_name=bucket_name)

            resolved_content_type = content_type or self._guess_content_type(
                object_name)
            data_stream = BytesIO(data)
            result = self.client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=data_stream,
                length=len(data),
                content_type=resolved_content_type,
            )

            assert result is not None
            url = f"http://{self.public_endpoint}/{bucket_name}/{object_name}"

            return UploadResult(url, bucket_name, object_name)

        except S3Error as e:
            error_msg = f"uploadfile '{object_name}' failed: {e}"
            logger.error(error_msg)
            raise StorageError(error_msg)

    async def aupload_file(
        self,
        bucket_name: str,
        object_name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> UploadResult:
        result = await asyncio.to_thread(
            self.upload_file, bucket_name=bucket_name, object_name=object_name, data=data, content_type=content_type
        )
        return result

    def upload_file_from_path(self, bucket_name: str, object_name: str, file_path: str) -> UploadResult:
        """Upload file from file path."""
        try:
            with open(file_path, "rb") as file_data:
                data = file_data.read()

            return self.upload_file(bucket_name, object_name, data)

        except FileNotFoundError:
            raise StorageError(f"file '{file_path}' does not exist")
        except Exception as e:
            raise StorageError(f"Failed to upload file from path: {e}")

    def _guess_content_type(self, object_name: str) -> str:
        """Guess MIME type from file name."""
        guessed_type, _ = mimetypes.guess_type(object_name)
        if guessed_type:
            return guessed_type

        ext = object_name.split(".")[-1].lower()
        content_types = {
            "md": "text/markdown",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "zip": "application/zip",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }
        return content_types.get(ext, "application/octet-stream")

    def download_file(self, bucket_name: str, object_name: str) -> bytes:
        """downloadfile"""
        try:
            response = self.client.get_object(
                bucket_name=bucket_name, object_name=object_name)
            data = response.read()
            response.close()
            logger.info(
                f"Successfully downloaded '{object_name}' from bucket '{bucket_name}'")
            return data

        except S3Error as e:
            if "NoSuchKey" in str(e):
                raise StorageError(
                    f"Object '{object_name}' does not exist in bucket '{bucket_name}'")
            raise StorageError(f"downloadfilefailed: {e}")

    async def adownload_response(self, bucket_name: str, object_name: str) -> BaseHTTPResponse:
        """Download file response asynchronously."""
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                bucket_name=bucket_name,
                object_name=object_name,
            )
            return response

        except S3Error as e:
            if "NoSuchKey" in str(e):
                raise StorageError(
                    f"Object '{object_name}' does not exist in bucket '{bucket_name}'")
            raise StorageError(f"downloadfilefailed: {e}")

    async def adownload_file(self, bucket_name: str, object_name: str) -> bytes:
        """Download file asynchronously."""
        try:
            response = await asyncio.to_thread(self.client.get_object, bucket_name=bucket_name, object_name=object_name)
            data = await asyncio.to_thread(response.read)
            response.close()
            logger.info(
                f"Successfully downloaded '{object_name}' from bucket '{bucket_name}'")
            return data

        except S3Error as e:
            if "NoSuchKey" in str(e):
                raise StorageError(
                    f"Object '{object_name}' does not exist in bucket '{bucket_name}'")
            raise StorageError(f"downloadfilefailed: {e}")

    def get_presigned_url(self, bucket_name: str, object_name: str, days=7) -> str:
        """Generate a presigned URL for external access when MinIO is in a private network."""
        res_url = self.client.get_presigned_url(
            method="GET", bucket_name=bucket_name, object_name=object_name, expires=timedelta(days=days)
        )
        return res_url

    def delete_file(self, bucket_name: str, object_name: str) -> bool:
        """deletefile"""
        try:
            self.client.remove_object(
                bucket_name=bucket_name, object_name=object_name)
            logger.info(
                f"Successfully deleted '{object_name}' from bucket '{bucket_name}'")
            return True

        except S3Error as e:
            if "NoSuchKey" in str(e):
                logger.warning(
                    f"Object to delete '{object_name}' does not exist")
                return False
            raise StorageError(f"deletefilefailed: {e}")

    async def adelete_file(self, bucket_name: str, object_name: str) -> bool:
        """deletefile"""
        result = await asyncio.to_thread(
            self.delete_file,
            bucket_name=bucket_name,
            object_name=object_name,
        )
        return result

    async def adelete_objects_by_prefix(self, bucket_name: str, prefix: str) -> int:
        """
        Delete objects by prefix.

        Args:
            bucket_name: bucket name
            prefix: object prefix

        Returns:
            number of deleted objects
        """
        deleted_count = 0

        def _delete_objects():
            nonlocal deleted_count
            try:
                objects = self.client.list_objects(
                    bucket_name, prefix=prefix, recursive=True)
                for obj in objects:
                    try:
                        self.client.remove_object(bucket_name, obj.object_name)
                        deleted_count += 1
                    except S3Error as e:
                        logger.warning(
                            f"Failed to delete {bucket_name}/{obj.object_name}: {e}")
            except S3Error as e:
                logger.warning(
                    f"Failed to list objects in {bucket_name}/{prefix}: {e}")

        await asyncio.to_thread(_delete_objects)
        return deleted_count

    async def adelete_bucket(self, bucket_name: str) -> bool:
        """
        Delete bucket (delete all objects first, then delete bucket).

        Args:
            bucket_name: bucket name

        Returns:
            whether successful
        """
        try:
            # Delete all objects first.
            await self.adelete_objects_by_prefix(bucket_name, "")
            # Then delete bucket.
            await asyncio.to_thread(self.client.remove_bucket, bucket_name)
            logger.info(f"successfuldelete bucket: {bucket_name}")
            return True
        except S3Error as e:
            if "NoSuchBucket" in str(e):
                logger.warning(f"bucket does not exist: {bucket_name}")
                return False
            raise StorageError(f"delete bucket failed: {e}")

    def file_exists(self, bucket_name: str, object_name: str) -> bool:
        """Check whether file exists."""
        try:
            self.client.stat_object(
                bucket_name=bucket_name, object_name=object_name)
            return True
        except S3Error as e:
            if "NoSuchKey" in str(e):
                return False
            raise StorageError(f"Failed to check file existence: {e}")

    def _ensure_public_read_access(self, bucket_name: str) -> None:
        """Set bucket policy to allow public read access."""
        if bucket_name not in self.PUBLIC_READ_BUCKETS:
            return

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                },
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:ListBucket"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}"],
                },
            ],
        }

        try:
            self.client.set_bucket_policy(
                bucket_name=bucket_name, policy=json.dumps(policy))
        except S3Error as e:
            logger.warning(
                f"Failed to set public read policy for bucket '{bucket_name}': {e}")
            raise StorageError(
                f"Unable to set public access policy for bucket: {e}")

    @asynccontextmanager
    async def temp_file_from_url(
        self,
        url: str,
        allowed_extensions: list[str] | None = None,
    ):
        """
        Async context manager: download a file from MinIO URL to a temporary file, then clean it up automatically.

        Args:
            url: MinIO file URL
            allowed_extensions: allowed file extensions (optional)

        Yields:
            str: temporary file path

        Raises:
            StorageError: if URL is invalid or download fails
        """
        import tempfile
        from urllib.parse import urlparse

        # verify URL
        if not url or not isinstance(url, str):
            raise StorageError("URL cannot be empty")

        url = url.strip()

        if not url.startswith(("http://", "https://")):
            raise StorageError("Invalid MinIO URL; only http/https is allowed")

        parsed = urlparse(url)

        # Verify host.
        endpoint_host = self.endpoint.split("://")[-1].split(":")[0]
        url_host = parsed.netloc.split(":")[0]

        if endpoint_host != url_host and url_host != os.environ.get("HOST_IP", "localhost"):
            raise StorageError(f"External URL not allowed: {url_host}")

        # Check path traversal.
        if ".." in url or "\\" in url:
            raise StorageError("URL contains path traversal characters")

        # Verify extension.
        if allowed_extensions and not any(url.endswith(ext) for ext in allowed_extensions):
            raise StorageError(
                f"File extension does not meet requirements; allowed: {', '.join(allowed_extensions)}")

        # Parse bucket and object name.
        path_parts = parsed.path.lstrip("/").split("/", 1)
        if len(path_parts) != 2:
            raise StorageError("Unable to parse MinIO URL")

        bucket_name, object_name = path_parts

        # Download file.
        file_data = await self.adownload_file(bucket_name, object_name)
        logger.info(
            f"Successfully downloaded file from MinIO: {object_name} ({len(file_data)} bytes)")

        # Create temporary file
        if allowed_extensions:
            suffix = next(
                (ext for ext in allowed_extensions if url.endswith(ext)), ".tmp")
        else:
            suffix = f".{object_name.split('.')[-1]}"

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as temp_file:
                temp_file.write(file_data)
                temp_path = temp_file.name

            logger.info(f"File downloaded to temporary path: {temp_path}")
            yield temp_path

        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    logger.info(f"Deleted temporary file: {temp_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temporary file: {e}")


# Global client instance
_default_client = None


def get_minio_client() -> MinIOClient:
    """Get MinIO client instance."""
    global _default_client
    if _default_client is None:
        _default_client = MinIOClient()
    return _default_client


async def aupload_file_to_minio(bucket_name: str, file_name: str, data: bytes) -> str:
    """
    Upload file bytes to MinIO via async interface and return resource URL.
    MIME type is inferred automatically by MinIO client from object_name.

    Args:
        bucket_name: bucket_name
        file_name : filename
        data: file bytes
    Returns:
        str: file access URL
    """
    client = get_minio_client()
    upload_result = await client.aupload_file(bucket_name, file_name, data)
    return upload_result.url
