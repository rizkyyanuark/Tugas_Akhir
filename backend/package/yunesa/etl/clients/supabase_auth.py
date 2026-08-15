from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from supabase import Client, create_client

from yunesa.etl.config import (
    SUPABASE_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    SUPABASE_WRITE_KEY,
)
from yunesa.etl.utils.logging import log_event, log_warning


def classify_supabase_key(key: str) -> str:
    """Return a non-secret label for the configured Supabase key."""
    if not key:
        return "missing"
    if key.startswith("sb_publishable_"):
        return "publishable"
    if key.startswith("sb_secret_"):
        return "secret"
    if key.count(".") == 2:
        try:
            payload = key.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
            role = json.loads(decoded.decode("utf-8")).get("role")
            return str(role or "jwt")
        except Exception:
            return "jwt"
    return "unknown"


def _patch_supabase_key_validation() -> tuple[Any, Any]:
    """Allow modern sb_publishable_/sb_secret_ keys in older supabase-py paths."""
    original_match = re.match

    def patched_match(pattern: str | re.Pattern, string: Any, flags: int = 0) -> Any:
        if isinstance(string, str) and (
            string.startswith("sb_publishable_") or string.startswith("sb_secret_")
        ):
            return True
        return original_match(pattern, string, flags)

    re.match = patched_match
    return re, original_match


def create_etl_supabase_client(
    *,
    url: str | None = None,
    key: str | None = None,
    require_write: bool = False,
    logger: logging.Logger | None = None,
) -> tuple[Client, str]:
    """Create a Supabase client using the correct key for ETL read/write jobs."""
    resolved_url = url or SUPABASE_URL
    resolved_key = key or (SUPABASE_WRITE_KEY if require_write else SUPABASE_KEY or SUPABASE_WRITE_KEY)

    if not resolved_url or not resolved_key:
        key_name = "SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY" if require_write else "SUPABASE_KEY"
        raise ValueError(f"SUPABASE_URL or {key_name} missing.")

    key_role = classify_supabase_key(resolved_key)
    if require_write and key_role in {"publishable", "anon"} and logger:
        log_warning(
            logger,
            "supabase.write_key_may_hit_rls",
            key_role=key_role,
            required="service_role_or_secret",
        )

    module, original_match = _patch_supabase_key_validation()
    try:
        client = create_client(resolved_url, resolved_key)
    finally:
        module.match = original_match

    if logger:
        log_event(
            logger,
            "supabase.client.connected",
            url=resolved_url[:40],
            key_role=key_role,
            service_role_configured=bool(SUPABASE_SERVICE_ROLE_KEY),
            write_mode=require_write,
        )

    return client, key_role
