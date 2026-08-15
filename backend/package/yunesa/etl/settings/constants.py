"""Static ETL constants used by cleaners and loaders."""

from __future__ import annotations

STRICT_AFFILIATION: str = "UNIVERSITAS NEGERI SURABAYA"

PREFIX_TITLES: frozenset[str] = frozenset(
    {
        "prof",
        "dr",
        "drs",
        "dra",
        "ir",
        "h",
        "hj",
        "apt",
        "ns",
        "bd",
        "kh",
        "r",
        "ra",
        "tb",
        "en",
        "rr",
        "rm",
        "andes",
    }
)

ID_COLUMN_TYPES: dict[str, type] = {
    "nip": str,
    "nidn": str,
    "scholar_id": str,
    "scopus_id": str,
    "sinta_id": str,
}

