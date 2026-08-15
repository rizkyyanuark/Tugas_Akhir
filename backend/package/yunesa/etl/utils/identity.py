from __future__ import annotations

from typing import Any

import pandas as pd


NULL_STRINGS = {"", "nan", "none", "null", "nat"}


def has_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() not in NULL_STRINGS


def clean_optional(value: Any) -> str | None:
    return str(value).strip() if has_value(value) else None


def merge_missing_fields(target: dict[str, Any], source: dict[str, Any], fields: list[str]) -> int:
    updated = 0
    for field in fields:
        if not has_value(target.get(field)) and has_value(source.get(field)):
            target[field] = source[field]
            updated += 1
    return updated


def append_source_tag(source: Any, tag: str) -> str:
    source_value = str(source or "").strip()
    if not source_value or source_value.lower() in NULL_STRINGS:
        return tag
    if tag in source_value.split("+"):
        return source_value
    return f"{source_value}+{tag}"
