"""
embedding_engine.py — SiliconFlow & Sentence-Transformers Embedding Engine
=============================================================================
Provides embedding generation, batching, and SQLite caching.
"""

from __future__ import annotations

import os
import time
import random
import json
import sqlite3
import logging
from array import array
from functools import lru_cache
from pathlib import Path
from typing import Any

from yunesa.knowledge.constants import (
    DEFAULT_EMBEDDING_PROVIDER,
)
from yunesa.knowledge.config import (
    _positive_env_int,
    _positive_env_float,
)
from yunesa.knowledge.utils.text_processing import (
    safe_str,
    normalize_text,
)

logger = logging.getLogger(__name__)


def _embedding_cache_path() -> Path | None:
    configured = os.getenv("YUNESA_EMBEDDING_CACHE_PATH", "").strip()
    if configured.lower() in {"0", "off", "false", "none", "disabled"}:
        return None
    if configured:
        return Path(configured)
    if Path("/app/data").is_dir():
        return Path("/app/data/kg/cache/embeddings.sqlite3")
    return None


class _EmbeddingCache:
    """Small persistent SQLite cache keyed by provider, model, and text hash."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT PRIMARY KEY,
                dimension INTEGER NOT NULL,
                vector BLOB NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def key(provider: str, model_name: str, text: str) -> str:
        import hashlib
        payload = f"{provider}\0{model_name}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if self.connection is None or not keys:
            return {}
        result: dict[str, list[float]] = {}
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            query = f"SELECT cache_key, dimension, vector FROM embeddings WHERE cache_key IN ({placeholders})"
            for cache_key, dimension, blob in self.connection.execute(query, batch):
                values = array("f")
                values.frombytes(blob)
                if len(values) == int(dimension):
                    result[str(cache_key)] = [float(value) for value in values]
        return result

    def put_many(self, values: dict[str, list[float]]) -> None:
        if self.connection is None or not values:
            return
        rows = []
        now = time.time()
        for cache_key, vector in values.items():
            packed = array("f", (float(value) for value in vector)).tobytes()
            rows.append((cache_key, len(vector), packed, now))
        self.connection.executemany(
            "INSERT OR REPLACE INTO embeddings(cache_key, dimension, vector, created_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        self.connection.commit()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "_EmbeddingCache":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


@lru_cache(maxsize=2)
def _load_sentence_transformer_model(model_name: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is required for local embedding model fallback."
        ) from exc
    return SentenceTransformer(model_name)


def _siliconflow_embeddings(
    texts: list[str],
    *,
    model_name: str,
    split_depth: int = 0,
) -> list[list[float]]:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise ValueError("Set SILICONFLOW_API_KEY first for SiliconFlow embeddings.")

    import requests

    url = os.getenv("SILICONFLOW_EMBEDDING_URL", "https://api.siliconflow.com/v1/embeddings")
    timeout = _positive_env_float("SILICONFLOW_EMBEDDING_TIMEOUT", 120.0)
    max_attempts = _positive_env_int("SILICONFLOW_EMBEDDING_MAX_ATTEMPTS", 5)
    base_delay = _positive_env_float("SILICONFLOW_EMBEDDING_RETRY_BASE_SECONDS", 2.0)
    max_delay = _positive_env_float("SILICONFLOW_EMBEDDING_RETRY_MAX_SECONDS", 30.0)
    max_split_depth = _positive_env_int("SILICONFLOW_EMBEDDING_MAX_SPLIT_DEPTH", 2)
    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        request_started = time.perf_counter()
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model_name, "input": texts},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = sorted(payload.get("data") or [], key=lambda item: int(item.get("index", 0)))
            vectors = [item.get("embedding") for item in data]
            if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
                raise RuntimeError(
                    f"SiliconFlow returned {len(vectors)} valid embeddings for {len(texts)} texts."
                )
            return vectors
        except requests.RequestException as exc:
            last_error = exc
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            retryable = status is None or status in retry_statuses
            elapsed = time.perf_counter() - request_started
            if retryable and attempt < max_attempts:
                retry_after = 0.0
                if response is not None:
                    try:
                        retry_after = float(response.headers.get("Retry-After", "0") or 0)
                    except (TypeError, ValueError):
                        retry_after = 0.0
                exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay = max(retry_after, exponential * random.uniform(0.8, 1.2))
                logger.warning(
                    "embedding.provider.retry | provider=siliconflow | model=%s | status=%s | "
                    "attempt=%s/%s | batch_size=%s | elapsed_seconds=%.3f | delay_seconds=%.3f",
                    model_name,
                    status or "network_error",
                    attempt,
                    max_attempts,
                    len(texts),
                    elapsed,
                    delay,
                )
                time.sleep(delay)
                continue

            if (
                status in {500, 502, 503, 504}
                and len(texts) > 1
                and split_depth < max_split_depth
            ):
                midpoint = len(texts) // 2
                logger.warning(
                    "embedding.provider.split | provider=siliconflow | model=%s | status=%s | "
                    "batch_size=%s | split_depth=%s",
                    model_name,
                    status,
                    len(texts),
                    split_depth + 1,
                )
                return _siliconflow_embeddings(
                    texts[:midpoint], model_name=model_name, split_depth=split_depth + 1
                ) + _siliconflow_embeddings(
                    texts[midpoint:], model_name=model_name, split_depth=split_depth + 1
                )
            raise
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_attempts:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.warning(
                    "embedding.provider.invalid_response | provider=siliconflow | model=%s | "
                    "attempt=%s/%s | batch_size=%s | error_type=%s | delay_seconds=%.3f",
                    model_name,
                    attempt,
                    max_attempts,
                    len(texts),
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
                continue
            raise

    raise RuntimeError("SiliconFlow embedding request exhausted retries.") from last_error


def _embed_texts(
    texts: list[str],
    *,
    provider: str,
    model_name: str,
    batch_size: int,
    normalize_embeddings: bool = False,
    progress_label: str = "",
) -> list[list[float]]:
    provider = normalize_text(provider).replace("-", "_") or DEFAULT_EMBEDDING_PROVIDER
    if provider in {"siliconflow", "silicon_flow"}:
        started = time.perf_counter()
        text_keys = [_EmbeddingCache.key(provider, model_name, text) for text in texts]
        unique_text_by_key = dict(zip(text_keys, texts))
        cache_path = _embedding_cache_path()
        progress_every = _positive_env_int("YUNESA_EMBEDDING_PROGRESS_EVERY_BATCHES", 25)

        with _EmbeddingCache(cache_path) as cache:
            vectors_by_key = cache.get_many(list(unique_text_by_key))
            missing_keys = [key for key in unique_text_by_key if key not in vectors_by_key]
            total_batches = (len(missing_keys) + batch_size - 1) // batch_size
            if progress_label:
                logger.info(
                    "embedding.collection.start | collection=%s | provider=%s | model=%s | "
                    "rows=%s | unique_texts=%s | cache_hits=%s | cache_misses=%s | "
                    "batch_size=%s | api_batches=%s | cache_path=%s",
                    progress_label,
                    provider,
                    model_name,
                    len(texts),
                    len(unique_text_by_key),
                    len(vectors_by_key),
                    len(missing_keys),
                    batch_size,
                    total_batches,
                    cache_path or "disabled",
                )

            for batch_index, start in enumerate(range(0, len(missing_keys), batch_size), start=1):
                batch_keys = missing_keys[start : start + batch_size]
                batch_texts = [unique_text_by_key[key] for key in batch_keys]
                batch_started = time.perf_counter()
                batch_vectors = _siliconflow_embeddings(batch_texts, model_name=model_name)
                new_values = dict(zip(batch_keys, batch_vectors))
                vectors_by_key.update(new_values)
                cache.put_many(new_values)

                if progress_label and (
                    batch_index == 1
                    or batch_index == total_batches
                    or batch_index % progress_every == 0
                ):
                    logger.info(
                        "embedding.collection.progress | collection=%s | batch=%s/%s | "
                        "embedded=%s/%s | batch_seconds=%.3f | elapsed_seconds=%.3f",
                        progress_label,
                        batch_index,
                        total_batches,
                        min(start + len(batch_keys), len(missing_keys)),
                        len(missing_keys),
                        time.perf_counter() - batch_started,
                        time.perf_counter() - started,
                    )

            missing_after = [key for key in text_keys if key not in vectors_by_key]
            if missing_after:
                raise RuntimeError(f"Embedding cache/result missing {len(missing_after)} vectors.")
            result = [vectors_by_key[key] for key in text_keys]

        if progress_label:
            logger.info(
                "embedding.collection.done | collection=%s | rows=%s | cache_hits=%s | "
                "api_embeddings=%s | duration_seconds=%.3f",
                progress_label,
                len(texts),
                len(unique_text_by_key) - len(missing_keys),
                len(missing_keys),
                time.perf_counter() - started,
            )
        return result

    if provider in {"sentence_transformers", "sentence_transformer", "local"}:
        model = _load_sentence_transformer_model(model_name)
        vectors = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=normalize_embeddings,
        )
        return [vector.astype("float32").tolist() for vector in vectors]

    raise ValueError(f"Unsupported embedding provider: {provider}")


def _embed_milvus_records(
    records_by_collection: dict[str, list[dict[str, Any]]],
    *,
    provider: str,
    model_name: str,
    batch_size: int,
    normalize_embeddings: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    embedded: dict[str, list[dict[str, Any]]] = {}
    for collection_name, rows in records_by_collection.items():
        if not rows:
            embedded[collection_name] = []
            continue
        texts = [safe_str(row.get("_embedding_text")) for row in rows]
        vectors = _embed_texts(
            texts,
            provider=provider,
            model_name=model_name,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            progress_label=collection_name,
        )
        embedded_rows = []
        for row, vector in zip(rows, vectors):
            clean_row = {key: value for key, value in row.items() if not key.startswith("_")}
            clean_row["embedding"] = [float(value) for value in vector]
            embedded_rows.append(clean_row)
        embedded[collection_name] = embedded_rows
    return embedded


def _embed_milvus_record_batch(
    rows: list[dict[str, Any]],
    *,
    provider: str,
    model_name: str,
    batch_size: int,
    normalize_embeddings: bool = False,
    progress_label: str = "",
) -> list[dict[str, Any]]:
    """Embed a small Milvus batch without materializing a full collection in RAM."""
    if not rows:
        return []
    texts = [safe_str(row.get("_embedding_text")) for row in rows]
    vectors = _embed_texts(
        texts,
        provider=provider,
        model_name=model_name,
        batch_size=batch_size,
        normalize_embeddings=normalize_embeddings,
        progress_label=progress_label,
    )
    embedded_rows: list[dict[str, Any]] = []
    for row, vector in zip(rows, vectors):
        clean_row = {key: value for key, value in row.items() if not key.startswith("_")}
        clean_row["embedding"] = [float(value) for value in vector]
        embedded_rows.append(clean_row)
    return embedded_rows


# Public API Aliases
EmbeddingCache = _EmbeddingCache
siliconflow_embeddings = _siliconflow_embeddings
embed_texts = _embed_texts
embed_milvus_records = _embed_milvus_records

