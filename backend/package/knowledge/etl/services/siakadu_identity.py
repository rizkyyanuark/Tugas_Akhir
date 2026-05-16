from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

import pandas as pd

from ..clients.siakadu_client import SiakaduClient
from ..config import ENABLE_SIAKADU, ID_COLUMN_TYPES, SIAKADU_PRODI_URLS
from ..utils.identity import append_source_tag, clean_optional, has_value
from ..utils.storage import path_exists, read_dataframe_csv
from ..utils.utils import normalize_name, save_final_csv
from .lecturer_paths import SCRAPE_SIAKADU_PATH, SIAKADU_COLUMNS, filter_active_configs

logger = logging.getLogger(__name__)


def fetch_siakadu_data(prodi_filter: str | None = None) -> pd.DataFrame:
    """
    Fetch lecturer NIP/NIDN identities from SIAKADU public prodi pages.

    SIAKADU is a raw identity source. The result is checkpointed separately so
    downstream enrichment can re-run without repeatedly hitting the website.
    """
    logger.info("[STEP 2b] SIAKADU IDENTITY COLLECTION")

    configs = _filter_configs(prodi_filter)

    if not ENABLE_SIAKADU:
        logger.info("SIAKADU enrichment disabled via ETL_ENABLE_SIAKADU=false.")
        df_empty = pd.DataFrame(columns=SIAKADU_COLUMNS)
        save_final_csv(df_empty, SCRAPE_SIAKADU_PATH, label="Step 2b: SIAKADU")
        return df_empty

    program_urls = {name: SIAKADU_PRODI_URLS.get(name, "") for _, name, *_ in configs}
    records = SiakaduClient().scrape(program_urls, configs)
    df_siakadu = pd.DataFrame(records, columns=SIAKADU_COLUMNS)

    save_final_csv(df_siakadu, SCRAPE_SIAKADU_PATH, label="Step 2b: SIAKADU")
    logger.info("Success: Fetched %s lecturer identities from SIAKADU.", len(df_siakadu))
    return df_siakadu


def enrich_with_siakadu(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing NIP/NIDN from SIAKADU public prodi pages."""
    if not ENABLE_SIAKADU:
        logger.info("[4a] SIAKADU: DISABLED. Skipping.")
        return df

    logger.info("Enriching NIP/NIDN from SIAKADU...")

    try:
        df_siakadu = load_siakadu_cache_or_fetch()
    except Exception as exc:
        logger.error("SIAKADU enrichment skipped because identity source failed: %s", exc)
        return df

    if df_siakadu.empty:
        logger.warning("SIAKADU enrichment skipped: no identity records available.")
        return df

    indexes = _build_siakadu_indexes(df_siakadu)
    updated_rows = 0
    updated_fields = 0
    conflicts = 0

    for idx, row in df.iterrows():
        candidate, score, match_type = _find_siakadu_match(row, indexes)
        if not candidate:
            continue

        row_updated = False
        for field in ("nip", "nidn"):
            incoming = candidate.get(field)
            current = row.get(field)

            if not has_value(current) and has_value(incoming):
                df.at[idx, field] = incoming
                row_updated = True
                updated_fields += 1
            elif has_value(current) and has_value(incoming) and str(current).strip() != str(incoming).strip():
                conflicts += 1

        if row_updated:
            updated_rows += 1
            df.at[idx, "source"] = append_source_tag(row.get("source"), "SIAKADU")
            df.at[idx, "identity_source"] = "SIAKADU"
            df.at[idx, "identity_match_type"] = match_type
            df.at[idx, "identity_match_score"] = round(score, 4)
            if candidate.get("source_url"):
                df.at[idx, "identity_source_url"] = candidate["source_url"]

    logger.info(
        "SIAKADU enriched %s rows (%s fields). Identity conflicts kept from existing sources: %s.",
        updated_rows,
        updated_fields,
        conflicts,
    )
    return df


def load_siakadu_cache_or_fetch() -> pd.DataFrame:
    if path_exists(SCRAPE_SIAKADU_PATH):
        return read_dataframe_csv(SCRAPE_SIAKADU_PATH, dtype=ID_COLUMN_TYPES)
    return fetch_siakadu_data()


def _filter_configs(prodi_filter: str | None) -> list[tuple]:
    configs = filter_active_configs(prodi_filter)
    if prodi_filter:
        if not configs:
            logger.warning("No active config found for prodi filter: %s", prodi_filter)
        else:
            logger.info("Filtering enabled: Only processing %s", prodi_filter)
    return configs


def _program_key(value: Any) -> str:
    normalized = normalize_name(str(value or ""))
    return re.sub(r"^(s1|s2|s3|d3|d4|profesi)\s+", "", normalized)


def _same_program(left: Any, right: Any) -> bool:
    if not has_value(left) or not has_value(right):
        return False

    left_norm = normalize_name(str(left))
    right_norm = normalize_name(str(right))
    return left_norm == right_norm or _program_key(left) == _program_key(right)


def _identity_record(row: pd.Series) -> dict[str, Any]:
    name = clean_optional(row.get("nama_dosen")) or clean_optional(row.get("nama_norm")) or ""
    return {
        "nama_dosen": name,
        "nama_norm": normalize_name(clean_optional(row.get("nama_norm")) or name),
        "nip": clean_optional(row.get("nip")),
        "nidn": clean_optional(row.get("nidn")),
        "prodi": clean_optional(row.get("prodi_name")) or clean_optional(row.get("prodi")),
        "source_url": clean_optional(row.get("source_url")),
    }


def _build_siakadu_indexes(df_siakadu: pd.DataFrame) -> dict[str, Any]:
    records = [_identity_record(row) for _, row in df_siakadu.iterrows()]
    records = [record for record in records if has_value(record.get("nip")) or has_value(record.get("nidn"))]

    by_nidn: dict[str, list[dict[str, Any]]] = {}
    by_nip: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}

    for record in records:
        if has_value(record.get("nidn")):
            by_nidn.setdefault(str(record["nidn"]), []).append(record)
        if has_value(record.get("nip")):
            by_nip.setdefault(str(record["nip"]), []).append(record)
        if has_value(record.get("nama_norm")):
            by_name.setdefault(str(record["nama_norm"]), []).append(record)

    return {"records": records, "by_nidn": by_nidn, "by_nip": by_nip, "by_name": by_name}


def _prefer_same_program(candidates: list[dict[str, Any]], prodi: Any) -> dict[str, Any]:
    for candidate in candidates:
        if _same_program(candidate.get("prodi"), prodi):
            return candidate
    return candidates[0]


def _find_siakadu_match(row: pd.Series, indexes: dict[str, Any]) -> tuple[dict[str, Any] | None, float, str]:
    row_nidn = clean_optional(row.get("nidn"))
    row_nip = clean_optional(row.get("nip"))
    row_prodi = clean_optional(row.get("prodi"))

    if row_nidn and row_nidn in indexes["by_nidn"]:
        return _prefer_same_program(indexes["by_nidn"][row_nidn], row_prodi), 1.0, "nidn"

    if row_nip and row_nip in indexes["by_nip"]:
        return _prefer_same_program(indexes["by_nip"][row_nip], row_prodi), 1.0, "nip"

    row_name = normalize_name(clean_optional(row.get("nama_norm")) or clean_optional(row.get("nama_dosen")) or "")
    if len(row_name) < 5:
        return None, 0.0, "none"

    exact_candidates = indexes["by_name"].get(row_name)
    if exact_candidates:
        candidate = _prefer_same_program(exact_candidates, row_prodi)
        score = 0.98 if _same_program(candidate.get("prodi"), row_prodi) else 0.94
        return candidate, score, "name_exact"

    best_candidate = None
    best_score = 0.0
    best_same_program = False
    for candidate in indexes["records"]:
        candidate_name = candidate.get("nama_norm") or ""
        if not candidate_name or candidate_name[0] != row_name[0]:
            continue

        score = SequenceMatcher(None, row_name, candidate_name).ratio()
        same_program = _same_program(candidate.get("prodi"), row_prodi)
        threshold = 0.90 if same_program else 0.94
        if score >= threshold and (score > best_score or (score == best_score and same_program and not best_same_program)):
            best_candidate = candidate
            best_score = score
            best_same_program = same_program

    if best_candidate:
        return best_candidate, best_score, "name_fuzzy"

    return None, 0.0, "none"
