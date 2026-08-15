from __future__ import annotations

from ..config import PRODI_WEB_CONFIG, SAVE_DIR
from ..utils.storage import build_path


# PRODI_WEB_CONFIG is already filtered by the enabled flag in config.py.
ACTIVE_CONFIGS = PRODI_WEB_CONFIG

ID_FIELDS = ["nip", "nidn", "scholar_id", "scopus_id", "sinta_id"]

SIAKADU_COLUMNS = [
    "nama_dosen",
    "nama_norm",
    "nama_original",
    "nip",
    "nidn",
    "scholar_id",
    "scopus_id",
    "sinta_id",
    "gender",
    "prodi_code",
    "prodi_name",
    "source_url",
    "source",
    "affiliation",
]

SCRAPE_WEB_PATH = build_path(SAVE_DIR, "raw_web_data.csv")
SCRAPE_PDDIKTI_PATH = build_path(SAVE_DIR, "raw_pddikti_data.csv")
SCRAPE_SIAKADU_PATH = build_path(SAVE_DIR, "raw_siakadu_data.csv")
LECTURER_MASTER_PATH = build_path(SAVE_DIR, "lecturer_master.csv")
MERGED_CSV = build_path(SAVE_DIR, "dosen_infokom_merged.csv")
FINAL_CSV = build_path(SAVE_DIR, "dosen_infokom_final.csv")
SCHOLAR_CSV = build_path(SAVE_DIR, "dosen_papers_scholar.csv")


def filter_active_configs(prodi_filter: str | None = None) -> list[tuple]:
    if not prodi_filter:
        return ACTIVE_CONFIGS
    return [config for config in ACTIVE_CONFIGS if config[0] == prodi_filter]
