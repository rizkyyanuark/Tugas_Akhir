from __future__ import annotations

from ..config import SAVE_DIR
from ..utils.storage import get_path_obj


SCOPUS_ARTIFACT = get_path_obj(SAVE_DIR, "papers/processed/sources/lecturer_papers_scopus.parquet")
SCOPUS_RAW_ARTIFACT = get_path_obj(SAVE_DIR, "papers/raw/lecturer_papers_scopus_raw.parquet")
SCHOLAR_RAW_ARTIFACT = get_path_obj(SAVE_DIR, "papers/raw/lecturer_papers_scholar_raw.parquet")
SCHOLAR_ARTIFACT = get_path_obj(SAVE_DIR, "papers/processed/sources/lecturer_papers_scholar.parquet")
SCHOLAR_TEMP_ARTIFACT = get_path_obj(SAVE_DIR, "papers/checkpoints/lecturer_papers_scholar_temp.parquet")
PAPER_MERGED_ARTIFACT = get_path_obj(SAVE_DIR, "papers/processed/lecturer_papers_merged.parquet")
PAPER_ENRICHED_ARTIFACT = get_path_obj(SAVE_DIR, "papers/checkpoints/lecturer_papers_merged_enriched.parquet")
PAPER_ENRICHMENT_STATE_JSON = get_path_obj(SAVE_DIR, "papers/state/paper_enrichment_checkpoint.json")

SCOPUS_SAMPLE_RAW_ARTIFACT = get_path_obj(SAVE_DIR, "papers/sample/sample_lecturer_papers_scopus_raw.parquet")
SCOPUS_SAMPLE_ARTIFACT = get_path_obj(SAVE_DIR, "papers/sample/sample_lecturer_papers_scopus.parquet")
SCHOLAR_SAMPLE_ARTIFACT = get_path_obj(SAVE_DIR, "papers/sample/sample_lecturer_papers_scholar.parquet")
PAPER_SAMPLE_TRANSFORMED_ARTIFACT = get_path_obj(SAVE_DIR, "papers/sample/sample_lecturer_papers_merged.parquet")
PAPER_SAMPLE_ENRICHED_ARTIFACT = get_path_obj(SAVE_DIR, "papers/sample/sample_lecturer_papers_merged_enriched.parquet")

# Existing flat CSV artifacts are kept as read fallbacks during migration.
LEGACY_SCOPUS_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scopus.csv")
LEGACY_SCOPUS_RAW_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scopus_raw.csv")
LEGACY_SCHOLAR_RAW_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scholar_raw.csv")
LEGACY_SCHOLAR_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scholar.csv")
LEGACY_SCHOLAR_TEMP_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scholar_temp.csv")
LEGACY_PAPER_MERGED_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_merged.csv")
LEGACY_PAPER_ENRICHED_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_merged_enriched.csv")

LEGACY_SCOPUS_SAMPLE_RAW_CSV = get_path_obj(SAVE_DIR, "sample_lecturer_papers_scopus_raw.csv")
LEGACY_SCOPUS_SAMPLE_CSV = get_path_obj(SAVE_DIR, "sample_lecturer_papers_scopus.csv")
LEGACY_SCHOLAR_SAMPLE_CSV = get_path_obj(SAVE_DIR, "sample_lecturer_papers_scholar.csv")
LEGACY_PAPER_SAMPLE_TRANSFORMED_CSV = get_path_obj(SAVE_DIR, "sample_lecturer_papers_merged.csv")
LEGACY_PAPER_SAMPLE_ENRICHED_CSV = get_path_obj(SAVE_DIR, "sample_lecturer_papers_merged_enriched.csv")

LEGACY_CSV_BY_ARTIFACT = {
    str(SCOPUS_ARTIFACT): LEGACY_SCOPUS_CSV,
    str(SCOPUS_RAW_ARTIFACT): LEGACY_SCOPUS_RAW_CSV,
    str(SCHOLAR_RAW_ARTIFACT): LEGACY_SCHOLAR_RAW_CSV,
    str(SCHOLAR_ARTIFACT): LEGACY_SCHOLAR_CSV,
    str(SCHOLAR_TEMP_ARTIFACT): LEGACY_SCHOLAR_TEMP_CSV,
    str(PAPER_MERGED_ARTIFACT): LEGACY_PAPER_MERGED_CSV,
    str(PAPER_ENRICHED_ARTIFACT): LEGACY_PAPER_ENRICHED_CSV,
    str(SCOPUS_SAMPLE_RAW_ARTIFACT): LEGACY_SCOPUS_SAMPLE_RAW_CSV,
    str(SCOPUS_SAMPLE_ARTIFACT): LEGACY_SCOPUS_SAMPLE_CSV,
    str(SCHOLAR_SAMPLE_ARTIFACT): LEGACY_SCHOLAR_SAMPLE_CSV,
    str(PAPER_SAMPLE_TRANSFORMED_ARTIFACT): LEGACY_PAPER_SAMPLE_TRANSFORMED_CSV,
    str(PAPER_SAMPLE_ENRICHED_ARTIFACT): LEGACY_PAPER_SAMPLE_ENRICHED_CSV,
}

# Backward-compatible names retained for callers while storage moves to Parquet.
SCOPUS_CSV = SCOPUS_ARTIFACT
SCOPUS_RAW_CSV = SCOPUS_RAW_ARTIFACT
SCHOLAR_RAW_CSV = SCHOLAR_RAW_ARTIFACT
SCHOLAR_CSV = SCHOLAR_ARTIFACT
SCHOLAR_TEMP_CSV = SCHOLAR_TEMP_ARTIFACT
PAPER_MERGED_CSV = PAPER_MERGED_ARTIFACT
PAPER_ENRICHED_CSV = PAPER_ENRICHED_ARTIFACT
SCOPUS_SAMPLE_RAW_CSV = SCOPUS_SAMPLE_RAW_ARTIFACT
SCOPUS_SAMPLE_CSV = SCOPUS_SAMPLE_ARTIFACT
SCHOLAR_SAMPLE_CSV = SCHOLAR_SAMPLE_ARTIFACT
PAPER_SAMPLE_TRANSFORMED_CSV = PAPER_SAMPLE_TRANSFORMED_ARTIFACT
PAPER_SAMPLE_MERGED_CSV = PAPER_SAMPLE_ENRICHED_ARTIFACT
