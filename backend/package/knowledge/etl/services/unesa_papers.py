import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

from knowledge.etl.clients.scholar_client import ScholarClient
from knowledge.etl.clients.supabase_client import SupabaseClient
from knowledge.etl.config import (
    BD_PASS_UNLOCKER,
    BD_USER_UNLOCKER,
    BRIGHT_DATA_HOST,
    ETL_ENRICH_MAX_PAPERS_PER_RUN,
    PROXY_URL,
    SCIVAL_EMAIL,
    SCIVAL_PASS,
)
from knowledge.etl.services.paper_paths import (
    PAPER_ENRICHED_CSV,
    PAPER_ENRICHMENT_STATE_JSON,
    PAPER_MERGED_CSV,
    PAPER_SAMPLE_MERGED_CSV,
    PAPER_SAMPLE_TRANSFORMED_CSV,
    LEGACY_CSV_BY_ARTIFACT,
    SCHOLAR_CSV,
    SCHOLAR_SAMPLE_CSV,
    SCHOLAR_TEMP_CSV,
    SCOPUS_CSV,
    SCOPUS_RAW_CSV,
    SCOPUS_SAMPLE_CSV,
    SCOPUS_SAMPLE_RAW_CSV,
)
from knowledge.etl.utils.storage import (
    path_name,
    read_dataframe_artifact,
    smart_exists,
    smart_unlink,
    write_dataframe_artifact,
    write_json_artifact,
)
from knowledge.etl.utils.logging import log_error, log_event, log_warning
from knowledge.etl.transform.enricher import (
    enrich_paper_batch,
    missing_required_enrichment_fields,
    resolve_academic_authors,
)

logger = logging.getLogger(__name__)


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _scholar_profile_proxy_url() -> str:
    """Prefer Web Unlocker for Google Scholar profile pages."""
    if BD_USER_UNLOCKER and BD_PASS_UNLOCKER and BRIGHT_DATA_HOST:
        return f"http://{BD_USER_UNLOCKER}:{BD_PASS_UNLOCKER}@{BRIGHT_DATA_HOST}"
    return PROXY_URL


def _legacy_csv_for_artifact(path: Path | str) -> Path | str | None:
    return LEGACY_CSV_BY_ARTIFACT.get(str(path))


def _artifact_exists(path: Path | str) -> bool:
    legacy_path = _legacy_csv_for_artifact(path)
    return smart_exists(path) or bool(legacy_path and smart_exists(legacy_path))


def _existing_artifact_path(path: Path | str) -> Path | str:
    if smart_exists(path):
        return path

    legacy_path = _legacy_csv_for_artifact(path)
    if legacy_path and smart_exists(legacy_path):
        log_event(logger, "artifact.legacy_fallback", requested=path, selected=legacy_path)
        return legacy_path
    return path


def _unlink_artifact(path: Path | str) -> None:
    smart_unlink(path)
    legacy_path = _legacy_csv_for_artifact(path)
    if legacy_path:
        smart_unlink(legacy_path)


def _read_artifact_or_empty(path: Path | str, **kwargs) -> pd.DataFrame:
    """Read a CSV/Parquet artifact, returning an empty DataFrame for empty CSVs."""
    try:
        return read_dataframe_artifact(_existing_artifact_path(path), **kwargs)
    except pd.errors.EmptyDataError:
        log_warning(logger, "artifact.empty", path=path,
                    action="treat_as_empty_dataframe")
        return pd.DataFrame()


def _limit_mixed_sources(df: pd.DataFrame, limit: Optional[int]) -> pd.DataFrame:
    """Return up to `limit` rows while preserving source diversity when possible."""
    if not limit or limit <= 0 or df.empty or len(df) <= limit:
        return df

    if "source" not in df.columns:
        return df.head(limit).copy()

    groups = {
        str(source): group.copy()
        for source, group in df.groupby(df["source"].fillna("").astype(str), sort=False)
    }
    selected_indices: list[int] = []
    while len(selected_indices) < limit and groups:
        exhausted: list[str] = []
        for source, group in groups.items():
            if group.empty:
                exhausted.append(source)
                continue
            selected_indices.append(group.index[0])
            groups[source] = group.iloc[1:]
            if len(selected_indices) >= limit:
                break
        for source in exhausted:
            groups.pop(source, None)

    return df.loc[selected_indices].reset_index(drop=True)


def _get_target_ids(df_lecturers: pd.DataFrame, col_name: str) -> List[str]:
    """Extract clean IDs from lecturer DataFrame."""
    if df_lecturers.empty:
        return []
    ids = df_lecturers[col_name].dropna().unique().tolist()
    return [str(x).strip().replace('.0', '') for x in ids if x and str(x).strip().lower() not in ('nan', 'none', '')]


def _paper_checkpoint_key(row: pd.Series) -> str:
    """Build a stable enrichment checkpoint key from title, then DOI."""
    title = re.sub(r"[^a-z0-9]+", "", str(row.get("Title", "")).lower())
    if title and title not in {"nan", "none", "null"}:
        return f"title:{title}"

    doi = str(row.get("DOI", "")).strip().lower()
    if doi and doi not in {"nan", "none", "null"}:
        return f"doi:{doi}"
    return ""


def _is_enriched(value) -> bool:
    return str(value).strip().lower() == "true"


def _ensure_enrichment_control_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure checkpoint/load control columns exist for paper enrichment."""
    for column in [
        "enriched",
        "enrichment_status",
        "missing_required_fields",
        "metadata_provenance",
    ]:
        if column not in df.columns:
            df[column] = ""
    return df


def _missing_required_fields_for_row(row: pd.Series) -> list[str]:
    return missing_required_enrichment_fields(
        abstract=row.get("Abstract", ""),
        keywords=row.get("Keywords", ""),
        author_ids=row.get("Author IDs", ""),
        tldr=row.get("TLDR", ""),
    )


def _is_complete_enrichment_row(row: pd.Series) -> bool:
    """Return True only when the row is safe to load to the paper KG tables."""
    missing = _missing_required_fields_for_row(row)
    status = str(row.get("enrichment_status", "")).strip().lower()
    return not missing and status != "failed_permanent"


def _complete_enrichment_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    df = _ensure_enrichment_control_columns(df)
    return df.apply(_is_complete_enrichment_row, axis=1)


def _resume_enrichment_checkpoint(df: pd.DataFrame, output_file: Path | str) -> pd.DataFrame:
    """
    Overlay checkpointed rows from the enriched checkpoint onto transformed input.

    The transformed dataset stays the source of truth for which papers belong in
    the run. Rows are restored by title-based checkpoint key so reruns can keep
    partial metadata and continue from the latest enrichment checkpoint.
    """
    if df.empty or not _artifact_exists(output_file):
        return df

    checkpoint = _read_artifact_or_empty(output_file, dtype=str).fillna("")
    if checkpoint.empty:
        return df
    checkpoint = _ensure_enrichment_control_columns(checkpoint)

    checkpoint_rows: dict[str, pd.Series] = {}
    complete_rows = 0
    for _, row in checkpoint.iterrows():
        key = _paper_checkpoint_key(row)
        if not key:
            continue
        checkpoint_rows[key] = row
        if _is_complete_enrichment_row(row):
            complete_rows += 1

    if not checkpoint_rows:
        log_event(
            logger,
            "paper.enrich.checkpoint_loaded",
            path=output_file,
            rows=len(checkpoint),
            restored_rows=0,
            complete_rows=0,
        )
        return df

    resumed = df.copy()
    for column in checkpoint.columns:
        if column not in resumed.columns:
            resumed[column] = ""

    restored_rows = 0
    for index, row in resumed.iterrows():
        checkpoint_row = checkpoint_rows.get(_paper_checkpoint_key(row))
        if checkpoint_row is None:
            continue

        for column, value in checkpoint_row.items():
            resumed.at[index, column] = value
        restored_rows += 1

    log_event(
        logger,
        "paper.enrich.checkpoint_loaded",
        path=output_file,
        rows=len(checkpoint),
        restored_rows=restored_rows,
        complete_rows=complete_rows,
    )
    return resumed


def _write_enrichment_state(
    *,
    input_file: Path | str,
    output_file: Path | str,
    df: pd.DataFrame,
    status: str,
    batch_rows: int = 0,
) -> None:
    """Persist a small state document beside Parquet enrichment checkpoints."""
    runtime_outputs = {str(PAPER_ENRICHED_CSV), str(PAPER_SAMPLE_MERGED_CSV)}
    if str(output_file) not in runtime_outputs:
        return

    df = _ensure_enrichment_control_columns(df)
    complete_mask = _complete_enrichment_mask(df)
    enriched_rows = int(complete_mask.sum())

    payload = {
        "checkpoint_version": 1,
        "pipeline": "paper_enrichment",
        "status": status,
        "input_artifact": str(input_file),
        "output_artifact": str(output_file),
        "artifact_format": path_name(output_file).rsplit(".", 1)[-1],
        "total_rows": int(len(df)),
        "enriched_rows": enriched_rows,
        "pending_rows": int(len(df) - enriched_rows),
        "last_batch_rows": int(batch_rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        write_json_artifact(payload, PAPER_ENRICHMENT_STATE_JSON)
        log_event(
            logger,
            "paper.enrich.state_saved",
            path=PAPER_ENRICHMENT_STATE_JSON,
            status=status,
            enriched_rows=enriched_rows,
            pending_rows=payload["pending_rows"],
        )
    except Exception as exc:
        log_warning(logger, "paper.enrich.state_failed", path=PAPER_ENRICHMENT_STATE_JSON, error=exc)


def _load_lecturers_from_supabase() -> pd.DataFrame:
    """Standardized loader for lecturer data from Self-Hosted PostgreSQL."""
    try:
        from knowledge.etl.clients.postgres_client import PostgresClient
        client = PostgresClient()
        df = client.get_lecturers_df()
        if df.empty:
            log_warning(logger, "postgres.lecturers.empty")
        return df
    except Exception as e:
        log_error(logger, "postgres.lecturers.load_failed", exc=e)
        return pd.DataFrame()


# ================================================================
# STEP 1: SCOPUS SCRAPING
# ================================================================
def run_scopus_scraping(
    df_lecturers: Optional[pd.DataFrame] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    run_mode: str = "incremental",
    sample_size: Optional[int] = None,
    output_raw_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Scrape papers from Scopus for all lecturers."""
    email = email or SCIVAL_EMAIL
    password = password or SCIVAL_PASS
    from knowledge.etl.clients.scopus_client import ScopusPaperClient

    log_event(logger, "scopus.extract.start",
              mode=run_mode, sample_size=sample_size)

    if df_lecturers is None:
        df_lecturers = _load_lecturers_from_supabase()

    target_ids = _get_target_ids(df_lecturers, 'scopus_id')
    log_event(logger, "scopus.extract.targets", target_count=len(target_ids))

    if not target_ids:
        log_warning(logger, "scopus.extract.no_targets", action="skip")
        return pd.DataFrame()

    if run_mode == "sample":
        target_ids = target_ids[:1]
        log_event(logger, "scopus.extract.sample_mode",
                  author_count=len(target_ids), paper_limit=sample_size)

    client = ScopusPaperClient(email, password)
    papers = client.run_scraper(target_ids)

    df_new = pd.DataFrame(papers) if papers else pd.DataFrame()
    if run_mode == "sample" and sample_size:
        df_new = df_new.head(sample_size).copy()

    raw_path = output_raw_path or (
        SCOPUS_SAMPLE_RAW_CSV if run_mode == "sample" else SCOPUS_RAW_CSV)
    if df_new.empty:
        log_warning(logger, "scopus.extract.no_rows", action="skip_empty_checkpoint")
        return df_new

    write_dataframe_artifact(df_new, raw_path, index=False)
    log_event(logger, "checkpoint.saved", source="scopus_raw",
              path=raw_path, rows=len(df_new))

    return df_new


# ================================================================
# STEP 2: SCOPUS PROCESSING (Clean + Dedup + TLDR Enrichment)
# ================================================================
def run_scopus_processing(input_raw_path: Optional[Path] = None, output_master_path: Optional[Path] = None) -> pd.DataFrame:
    """Process Scopus data: Clean, Deduplicate, and Enrich."""
    from knowledge.etl.clients.scopus_client import process_scopus_data

    log_event(logger, "scopus.process.start",
              input_path=input_raw_path, output_path=output_master_path)

    raw_path = input_raw_path or SCOPUS_RAW_CSV
    master_path = output_master_path or SCOPUS_CSV

    if not _artifact_exists(raw_path):
        log_event(logger, "scopus.process.raw_missing",
                  path=raw_path, action="skip")
        return pd.DataFrame()

    df_raw = _read_artifact_or_empty(raw_path, dtype=str).fillna("")
    if df_raw.empty:
        log_warning(logger, "scopus.process.raw_empty",
                    path=raw_path, action="delete_and_skip")
        _unlink_artifact(raw_path)
        return pd.DataFrame()

    df_master = pd.DataFrame()
    if _artifact_exists(master_path):
        log_event(logger, "scopus.process.master_loaded", path=master_path)
        df_master = _read_artifact_or_empty(master_path, dtype=str).fillna("")
    else:
        log_event(logger, "scopus.process.master_missing",
                  action="start_fresh")

    log_event(logger, "scopus.process.merge_input",
              new_rows=len(df_raw), master_rows=len(df_master))
    df_combined = pd.concat([df_master, df_raw], ignore_index=True)

    if df_combined.empty:
        log_warning(logger, "scopus.process.no_rows", action="skip")
        return pd.DataFrame()

    df_processed = process_scopus_data(df_combined)

    write_dataframe_artifact(df_processed, master_path, index=False)
    log_event(logger, "checkpoint.saved", source="scopus_processed",
              path=master_path, rows=len(df_processed))

    _unlink_artifact(raw_path)
    return df_processed


# ================================================================
# STEP 3: SUPABASE INSERT (Upsert + Link to Lecturers)
# ================================================================
def run_supabase_insert(
    input_master_path: Optional[Path] = None,
    source_paths: Optional[list[tuple[Path | str, str]]] = None,
    sample_limit: Optional[int] = None,
) -> dict[str, int]:
    """Upsert cleaned Scopus and Scholar papers into Self-Hosted PostgreSQL."""
    log_event(logger, "paper.load.start",
              input_path=input_master_path, sample_limit=sample_limit)

    if input_master_path:
        sources = [(input_master_path, "custom")]
    elif source_paths:
        sources = source_paths
    else:
        sources = [(SCOPUS_CSV, "scopus"), (SCHOLAR_CSV, "scholar")]

    frames: list[pd.DataFrame] = []
    for csv_path, source_name in sources:
        if not _artifact_exists(csv_path):
            log_event(logger, "paper.load.source_missing",
                      path=csv_path, source=source_name, action="skip")
            continue

        log_event(logger, "paper.load.source_read",
                  path=csv_path, source=source_name)
        df_source = _read_artifact_or_empty(csv_path, dtype=str).fillna("")
        if df_source.empty:
            log_event(logger, "paper.load.source_empty",
                      path=csv_path, source=source_name, action="skip")
            continue
        if "source" not in df_source.columns:
            df_source["source"] = source_name
        else:
            df_source["source"] = df_source["source"].replace("", source_name)
        frames.append(df_source)

    if not frames:
        log_warning(logger, "paper.load.no_sources", action="skip")
        return {"papers": 0, "links": 0}

    df_master = pd.concat(frames, ignore_index=True)
    log_event(logger, "paper.load.rows_loaded",
              rows=len(df_master), sources=len(frames))

    try:
        from knowledge.etl.clients.postgres_client import PostgresClient
        from knowledge.etl.transform.cleaner import clean_papers_batch
        from knowledge.etl.transform.deduplicator import deduplicate_papers

        df_master = clean_papers_batch(df_master)
        df_master = deduplicate_papers(df_master)
        df_master = _limit_mixed_sources(df_master, sample_limit)
        df_master = _ensure_enrichment_control_columns(df_master)
        complete_mask = _complete_enrichment_mask(df_master)
        skipped_incomplete = int((~complete_mask).sum())
        if skipped_incomplete:
            missing_summary = (
                df_master.loc[~complete_mask]
                .apply(lambda row: ",".join(_missing_required_fields_for_row(row)) or "unknown", axis=1)
                .value_counts()
                .head(5)
                .to_dict()
            )
            log_warning(
                logger,
                "paper.load.skip_incomplete",
                rows=skipped_incomplete,
                reason="missing_required_enrichment_fields",
                missing_summary=missing_summary,
            )
        df_master = df_master.loc[complete_mask].reset_index(drop=True)
        log_event(logger, "paper.load.rows_ready", rows=len(df_master), skipped_incomplete=skipped_incomplete)
        if df_master.empty:
            log_warning(logger, "paper.load.no_complete_rows", action="skip_postgres_write")
            return {"papers": 0, "links": 0}

        loader = PostgresClient()
        log_event(logger, "paper.load.upsert_papers.start",
                  rows=len(df_master), table="papers")
        loader.upsert_papers(df_master)
        papers_count = len(df_master)
        links_count = 0

        log_event(logger, "paper.load.done",
                  papers=papers_count, links=links_count)
        return {"papers": papers_count, "links": links_count}

    except Exception as e:
        log_error(logger, "paper.load.failed", exc=e)
        raise


# ================================================================
# STEP 4: GOOGLE SCHOLAR SCRAPING (via ScholarClient)
# ================================================================


def run_scholar_scraping(
    proxy_url: Optional[str] = None,
    limit_per_author: int = 500,
    test_target_id: Optional[str] = None,
    run_mode: str = "incremental",
    sample_size: Optional[int] = None,
    paper_limit: Optional[int] = None,
    output_csv: Optional[Path] = None,
) -> Optional[pd.DataFrame]:
    """
    Scrape papers from Google Scholar profile pages via BrightData proxy.

    3-Phase Architecture:
        Phase 1: Pure Scrape - Fetch all papers from Scholar profile HTML.
        Phase 2: Batch Dedup - Remove duplicates vs Scopus + cross-lecturer.
        Phase 3: Batch Author Match - Match author names to lecturer database.

    Run Modes:
        full        -> Scrape ALL lecturers from scratch.
        incremental -> Skip lecturers already present in scholar CSV.
        sample      -> Process only `sample_size` lecturers.
    """
    scholar_proxy_url = proxy_url or _scholar_profile_proxy_url()
    if not scholar_proxy_url:
        log_error(
            logger,
            "scholar.extract.missing_proxy",
            message="BrightData Scholar proxy is required",
            required="BD_USER_UNLOCKER,BD_PASS_UNLOCKER or BD_USER_SERP,BD_PASS_SERP",
        )
        return None

    log_event(
        logger,
        "scholar.extract.start",
        mode=run_mode,
        sample_size=sample_size,
        limit_per_author=limit_per_author,
        paper_limit=paper_limit,
    )

    # Clear temp checkpoint file on full run mode to start fresh
    if run_mode == "full" and _artifact_exists(SCHOLAR_TEMP_CSV):
        log_event(logger, "scholar.extract.clear_temp_on_full_mode", path=path_name(SCHOLAR_TEMP_CSV))
        _unlink_artifact(SCHOLAR_TEMP_CSV)

    # --- Load Lecturer Data from Supabase ---
    df_lecturers = _load_lecturers_from_supabase()
    if df_lecturers.empty:
        log_error(logger, "scholar.extract.no_lecturers",
                  message="No lecturer data available from Supabase")
        return None

    targets = []
    for _, row in df_lecturers.iterrows():
        sid = str(row.get("scholar_id", "")).strip().replace('.0', '')
        if sid and sid.lower() not in ("", "nan", "none"):
            targets.append({"id": sid, "name": row["nama_dosen"]})

    # Incremental logic: Skip already-scraped authors
    already_scraped_ids = set()
    if run_mode == "incremental" and _artifact_exists(SCHOLAR_CSV):
        try:
            df_existing = _read_artifact_or_empty(SCHOLAR_CSV, dtype=str).fillna("")
            if "scrape_complete" in df_existing.columns:
                complete_mask = df_existing["scrape_complete"].apply(_truthy)
                already_scraped_ids = set(
                    df_existing.loc[complete_mask, "scholar_id"].unique().astype(str)
                )
                partial_authors = int(df_existing.loc[~complete_mask, "scholar_id"].nunique())
            else:
                partial_authors = (
                    int(df_existing["scholar_id"].nunique())
                    if "scholar_id" in df_existing.columns
                    else 0
                )
                log_warning(
                    logger,
                    "scholar.extract.incremental_state_legacy",
                    message="Existing Scholar artifact has no scrape_complete column; authors will be rechecked.",
                    path=path_name(SCHOLAR_CSV),
                    legacy_authors=partial_authors,
                )
            log_event(
                logger,
                "scholar.extract.incremental_state",
                complete_authors=len(already_scraped_ids),
                partial_authors=partial_authors,
                path=path_name(SCHOLAR_CSV),
            )
        except Exception as e:
            log_warning(
                logger, "scholar.extract.incremental_state_failed", error=e)

    if test_target_id:
        targets = [t for t in targets if t['id'] == test_target_id]
        log_event(logger, "scholar.extract.test_target",
                  scholar_id=test_target_id)
    elif run_mode == "incremental" and already_scraped_ids:
        total_before = len(targets)
        targets = [t for t in targets if t["id"] not in already_scraped_ids]
        skipped = total_before - len(targets)
        log_event(logger, "scholar.extract.incremental_filter",
                  skipped_authors=skipped, target_authors=len(targets))
        if not targets:
            log_event(logger, "scholar.extract.all_authors_scraped",
                      override="--mode full")
            return None
    elif run_mode == "sample" and sample_size:
        targets = targets[:sample_size]
        log_event(logger, "scholar.extract.sample_mode",
                  target_authors=len(targets))

    # ------------------------------------------------------------------
    # PHASE 1: PURE SCRAPE (No Filter, Auto-Save)
    # ------------------------------------------------------------------
    log_event(logger, "scholar.extract.phase", phase="scrape")
    scraped_ids = set()
    all_raw_papers = []
    if run_mode != "sample" and _artifact_exists(SCHOLAR_TEMP_CSV) and not test_target_id:
        try:
            df_temp = _read_artifact_or_empty(
                SCHOLAR_TEMP_CSV, dtype=str).fillna("")
            all_raw_papers = df_temp.to_dict('records')
            if "scrape_complete" in df_temp.columns:
                complete_mask = df_temp["scrape_complete"].apply(_truthy)
                scraped_ids = set(df_temp.loc[complete_mask, 'scholar_id'].unique())
            else:
                scraped_ids = set()
            log_event(logger, "scholar.extract.resume", rows=len(
                all_raw_papers), complete_authors=len(scraped_ids), path=SCHOLAR_TEMP_CSV)
        except Exception:
            pass

    total_api_calls = 0
    newly_scraped = 0

    client = ScholarClient(proxy_url=scholar_proxy_url)
    from urllib.parse import urlparse, parse_qs

    for i, target in enumerate(targets):
        if paper_limit and len(all_raw_papers) >= paper_limit:
            log_event(
                logger,
                "scholar.extract.paper_limit_reached",
                paper_limit=paper_limit,
                rows=len(all_raw_papers),
                action="stop_scraping",
            )
            break

        if target['id'] in scraped_ids:
            log_event(
                logger,
                "scholar.extract.author_skip",
                index=i + 1,
                total=len(targets),
                scholar_id=target["id"],
                reason="already_processed",
            )
            continue

        log_event(
            logger,
            "scholar.extract.author_start",
            index=i + 1,
            total=len(targets),
            lecturer=target["name"],
            scholar_id=target["id"],
        )

        articles = client.get_papers(target["id"], limit=limit_per_author)
        fetch_status = dict(client.last_fetch_status or {})
        total_api_calls += max(1, len(articles) // 100)
        scrape_complete = bool(fetch_status.get("complete"))
        scrape_method = str(fetch_status.get("method", "unknown"))
        scrape_reason = str(fetch_status.get("reason", "unknown"))

        if articles and not scrape_complete:
            log_warning(
                logger,
                "scholar.extract.author_partial",
                scholar_id=target["id"],
                rows=len(articles),
                limit_per_author=limit_per_author,
                method=scrape_method,
                reason=scrape_reason,
                action="will_retry_in_next_incremental_run",
            )
        elif not articles:
            log_warning(
                logger,
                "scholar.extract.author_empty",
                scholar_id=target["id"],
                method=scrape_method,
                reason=scrape_reason,
                action="will_retry_in_next_incremental_run",
            )

        for art in articles:
            if paper_limit and len(all_raw_papers) >= paper_limit:
                break

            # Reconstruct citation ID (if available in link) or use link hash
            link = art.get("link", "")
            cid = art.get("citation_id", "")
            if not cid and link:
                qs = parse_qs(urlparse(link).query)
                if 'citation_for_view' in qs:
                    cid = qs['citation_for_view'][0]

            all_raw_papers.append({
                "Title": art.get('title', ''),
                "Year": str(art.get("year", "")),
                "Journal": art.get("journal", ""),
                "Link": link,
                "Authors_raw": art.get("authors", ""),
                "citation_id": cid,
                "scholar_id": target["id"],
                "lecturer_name": target["name"],
                "source": "scholar",
                "scrape_complete": str(scrape_complete).lower(),
                "scrape_method": scrape_method,
                "scrape_reason": scrape_reason,
                "scrape_rows": str(len(articles)),
            })

        log_event(logger, "scholar.extract.author_done",
                  scholar_id=target["id"], rows=len(articles), complete=scrape_complete,
                  method=scrape_method, reason=scrape_reason)
        newly_scraped += 1

        if not test_target_id and newly_scraped % 5 == 0:
            df_temp = pd.DataFrame(all_raw_papers)
            for col in ["scrape_complete", "scrape_method", "scrape_reason", "scrape_rows"]:
                if col in df_temp.columns:
                    df_temp[col] = df_temp[col].fillna("").astype(str)
            write_dataframe_artifact(
                df_temp,
                SCHOLAR_TEMP_CSV,
                index=False,
            )
            log_event(logger, "checkpoint.saved", source="scholar_temp",
                      path=SCHOLAR_TEMP_CSV, rows=len(all_raw_papers))

        time.sleep(0.5)

    if not all_raw_papers:
        log_warning(logger, "scholar.extract.no_papers", action="skip")
        return None

    df_raw = pd.DataFrame(all_raw_papers)

    # ------------------------------------------------------------------
    # PHASE 2: BATCH DEDUP
    # ------------------------------------------------------------------
    log_event(logger, "scholar.extract.phase", phase="deduplicate")

    def _normalize_title(text):
        if pd.isna(text):
            return ""
        return re.sub(r'[^a-z0-9]', '', str(text).lower())

    # Load Scopus for cross-source dedup
    scopus_titles = set()
    if _artifact_exists(SCOPUS_CSV):
        try:
            df_scopus = _read_artifact_or_empty(SCOPUS_CSV)
            scopus_titles = set(df_scopus['Title'].apply(_normalize_title))
            log_event(logger, "scholar.extract.scopus_titles_loaded",
                      titles=len(scopus_titles))
        except Exception:
            pass

    df_raw['_norm_title'] = df_raw['Title'].apply(_normalize_title)

    # Keep duplicates at extract time. Transform-level dedup merges author IDs
    # into one paper node, so dropping here would lose lecturer relationships.
    df_raw["duplicate_of_scopus"] = df_raw["_norm_title"].isin(scopus_titles)
    log_event(
        logger,
        "scholar.extract.duplicates_preserved",
        matched_scopus=int(df_raw["duplicate_of_scopus"].sum()),
        duplicate_title_rows=int(df_raw.duplicated(subset="_norm_title").sum()),
        action="merge_author_relations_in_transform",
    )

    # ------------------------------------------------------------------
    # PHASE 3: AUTHOR RESOLUTION
    # ------------------------------------------------------------------
    log_event(logger, "scholar.extract.phase", phase="author_resolution")

    authors_resolved = []
    ids_resolved = []

    for idx, row in df_raw.iterrows():
        raw_authors = str(row.get("Authors_raw", ""))
        paper_sid = str(row.get("scholar_id", ""))

        # Use centralized logic from enricher
        final_names, final_ids = resolve_academic_authors(
            authors_str=raw_authors,
            paper_scholar_id=paper_sid
        )
        authors_resolved.append(final_names)
        ids_resolved.append(final_ids)

    df_raw['Authors'] = authors_resolved
    df_raw['Author IDs'] = ids_resolved

    # Cleanup and schema finalization
    df_final = df_raw.drop(columns=['_norm_title'])
    cols_to_add = ["Abstract", "Keywords", "Document Type", "DOI", "TLDR"]
    for col in cols_to_add:
        if col not in df_final.columns:
            df_final[col] = ""

    # Reorder columns
    ordered_cols = [
        "Authors", "Author IDs", "Title", "Year", "Journal", "Link",
        "Abstract", "Keywords", "Document Type", "DOI", "TLDR",
        "citation_id", "scholar_id", "lecturer_name", "source",
        "scrape_complete", "scrape_method", "scrape_reason", "scrape_rows",
    ]
    df_final = df_final[[c for c in ordered_cols if c in df_final.columns]]
    if paper_limit:
        df_final = df_final.head(paper_limit).copy()

    for col in ["scrape_complete", "scrape_method", "scrape_reason", "scrape_rows"]:
        if col in df_final.columns:
            df_final[col] = df_final[col].fillna("").astype(str)

    # ------------------------------------------------------------------
    # SAVE & OUTPUT
    # ------------------------------------------------------------------
    if test_target_id:
        log_event(logger, "scholar.extract.test_mode_no_save",
                  rows=len(df_final))
        return df_final

    output_file = output_csv or (
        SCHOLAR_SAMPLE_CSV if run_mode == "sample" else SCHOLAR_CSV)

    if run_mode == "incremental" and output_file == SCHOLAR_CSV and _artifact_exists(SCHOLAR_CSV):
        try:
            df_existing = _read_artifact_or_empty(output_file)
            df_combined = pd.concat([df_existing, df_final], ignore_index=True)
            for col in ["scrape_complete", "scrape_method", "scrape_reason", "scrape_rows"]:
                if col in df_combined.columns:
                    df_combined[col] = df_combined[col].fillna("").astype(str)
            if "scrape_complete" in df_combined.columns:
                df_combined["_scrape_complete_sort"] = df_combined["scrape_complete"].apply(
                    _truthy
                )
                df_combined = df_combined.sort_values(
                    by=["_scrape_complete_sort"],
                    ascending=False,
                    kind="stable",
                ).drop(columns=["_scrape_complete_sort"])
            df_combined = df_combined.drop_duplicates(
                subset='Title', keep='first')  # Basic dedup on merge
            write_dataframe_artifact(df_combined, output_file, index=False)
            log_event(logger, "checkpoint.saved", source="scholar_incremental",
                      path=output_file, rows=len(df_combined))
        except Exception as e:
            log_error(logger, "scholar.extract.incremental_merge_failed",
                      exc=e, path=output_file)
            write_dataframe_artifact(df_final, output_file, index=False)
    else:
        write_dataframe_artifact(df_final, output_file, index=False)
        log_event(logger, "checkpoint.saved", source="scholar",
                  path=output_file, rows=len(df_final))

    if run_mode != "sample":
        _unlink_artifact(SCHOLAR_TEMP_CSV)
    return df_final


def run_paper_transform(
    source_paths: Optional[list[tuple[Path | str, str]]] = None,
    output_csv: Optional[Path | str] = None,
    sample_limit: Optional[int] = None,
) -> pd.DataFrame:
    """Merge, clean, and deduplicate paper sources without external enrichment."""
    from knowledge.etl.transform.cleaner import clean_papers_batch
    from knowledge.etl.transform.deduplicator import deduplicate_papers

    frames: list[pd.DataFrame] = []
    sources = source_paths or [
        (SCOPUS_CSV, "scopus"), (SCHOLAR_CSV, "scholar")]
    output_file = output_csv or PAPER_MERGED_CSV

    for csv_path, source_name in sources:
        if not _artifact_exists(csv_path):
            log_event(logger, "paper.transform.source_missing",
                      path=csv_path, source=source_name, action="skip")
            continue
        df_source = _read_artifact_or_empty(csv_path, dtype=str).fillna("")
        if df_source.empty:
            log_event(logger, "paper.transform.source_empty",
                      path=csv_path, source=source_name, action="skip")
            continue
        if "source" not in df_source.columns:
            df_source["source"] = source_name
        else:
            df_source["source"] = df_source["source"].replace("", source_name)
        frames.append(df_source)

    if not frames:
        log_warning(logger, "paper.transform.no_sources", action="skip")
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = clean_papers_batch(df)
    df = deduplicate_papers(df)
    df = _limit_mixed_sources(df, sample_limit)

    if df.empty:
        write_dataframe_artifact(df, output_file, index=False)
        return df

    df = _ensure_enrichment_control_columns(df)

    write_dataframe_artifact(df, output_file, index=False)
    log_event(logger, "checkpoint.saved", source="paper_transformed",
              path=output_file, rows=len(df))
    return df


def run_paper_enrichment(
    input_csv: Optional[Path | str] = None,
    output_csv: Optional[Path | str] = None,
    sample_limit: Optional[int] = None,
    allow_paid_proxy: bool = True,
) -> pd.DataFrame:
    """Enrich transformed paper rows with metadata, KG TLDR, and author IDs."""
    input_file = input_csv or PAPER_MERGED_CSV
    output_file = output_csv or PAPER_ENRICHED_CSV

    if not _artifact_exists(input_file):
        log_error(logger, "paper.enrich.input_missing",
                  path=input_file, action="skip")
        return pd.DataFrame()

    df = _read_artifact_or_empty(input_file, dtype=str).fillna("")
    if df.empty:
        log_warning(logger, "paper.enrich.input_empty",
                    path=input_file, action="skip")
        return pd.DataFrame()

    df = _limit_mixed_sources(df, sample_limit)
    df = _resume_enrichment_checkpoint(df, output_file)
    df = _ensure_enrichment_control_columns(df)
    if "TLDR" not in df.columns:
        df["TLDR"] = ""

    pending_mask = ~_complete_enrichment_mask(df)
    pending_count = int(pending_mask.sum())
    if pending_count == 0:
        log_event(logger, "paper.enrich.no_pending_rows", action="skip")
    else:
        max_per_run = sample_limit or ETL_ENRICH_MAX_PAPERS_PER_RUN
        target_count = pending_count if max_per_run <= 0 else min(max_per_run, pending_count)
        complete_before = int((~pending_mask).sum())
        attempted_count = 0

        log_event(
            logger,
            "paper.enrich.target",
            pending_rows=pending_count,
            target_rows=target_count,
            max_per_run=max_per_run,
        )

        while attempted_count < target_count:
            batch_size = min(50, target_count - attempted_count)
            current_complete = int(_complete_enrichment_mask(df).sum())
            completed_during_run = max(0, current_complete - complete_before)
            start_idx = max(0, attempted_count - completed_during_run)
            df = enrich_paper_batch(
                df,
                batch_size=batch_size,
                start_idx=start_idx,
                allow_paid_proxy=allow_paid_proxy,
            )

            write_dataframe_artifact(df, output_file, index=False)
            log_event(logger, "checkpoint.saved", source="paper_enriched_batch", path=output_file, rows=len(df))
            _write_enrichment_state(
                input_file=input_file,
                output_file=output_file,
                df=df,
                status="running",
                batch_rows=batch_size,
            )

            attempted_count += batch_size

    df = _limit_mixed_sources(df, sample_limit)

    write_dataframe_artifact(df, output_file, index=False)
    final_pending = int((~_complete_enrichment_mask(df)).sum())
    _write_enrichment_state(
        input_file=input_file,
        output_file=output_file,
        df=df,
        status="completed" if final_pending == 0 else "partial",
    )
    log_event(logger, "checkpoint.saved", source="paper_enriched",
              path=output_file, rows=len(df))
    return df


def run_combined_sample_enrichment(sample_limit: int = 5) -> pd.DataFrame:
    """Backward-compatible sample helper: transform sample sources, then enrich them."""
    run_paper_transform(
        source_paths=[(SCOPUS_SAMPLE_CSV, "scopus"),
                      (SCHOLAR_SAMPLE_CSV, "scholar")],
        output_csv=PAPER_SAMPLE_TRANSFORMED_CSV,
        sample_limit=sample_limit,
    )
    return run_paper_enrichment(
        input_csv=PAPER_SAMPLE_TRANSFORMED_CSV,
        output_csv=PAPER_SAMPLE_MERGED_CSV,
        sample_limit=sample_limit,
    )


# ================================================================
# STEP 5: SCHOLAR ENRICHMENT (Keywords, Abstract, DOI, TLDR)
# ================================================================

def run_scholar_enrichment(
    input_csv: Optional[Path] = None,
    output_csv: Optional[Path] = None,
    test_limit: Optional[int] = None
) -> pd.DataFrame:
    """
    Enrich papers with Keywords, Abstract, DOI, TLDR, and Author IDs.
    Uses the centralized enrich_paper_batch service for multi-source enrichment.

    Args:
        input_csv: Path to input CSV (default: SCHOLAR_CSV)
        output_csv: Path to output CSV (default: SCHOLAR_CSV)
        test_limit: Max number of papers to enrich in this run.
    """
    log_event(logger, "scholar.enrich.start", input_path=input_csv,
              output_path=output_csv, test_limit=test_limit)

    input_file = input_csv or SCHOLAR_CSV
    output_file = output_csv or SCHOLAR_CSV

    if not _artifact_exists(input_file):
        log_error(logger, "scholar.enrich.input_missing",
                  path=input_file, action="skip")
        return pd.DataFrame()

    try:
        df = _read_artifact_or_empty(input_file, dtype=str).fillna("")
    except Exception as e:
        log_error(logger, "scholar.enrich.read_failed", exc=e, path=input_file)
        return pd.DataFrame()

    # Migration: Handle legacy 'Scraped_By_Pipeline' flag
    if 'Scraped_By_Pipeline' in df.columns and 'enriched' not in df.columns:
        df = df.rename(columns={'Scraped_By_Pipeline': 'enriched'})
        log_event(logger, "scholar.enrich.legacy_column_migrated",
                  from_column="Scraped_By_Pipeline", to_column="enriched")

    total_papers = len(df)
    enriched_mask = df.get("enriched", "").astype(str).str.lower() == "true"
    already_enriched = len(df[enriched_mask])
    remaining = total_papers - already_enriched

    log_event(
        logger,
        "scholar.enrich.status",
        total_rows=total_papers,
        enriched_rows=already_enriched,
        pending_rows=remaining,
    )

    if remaining == 0:
        log_event(logger, "scholar.enrich.no_pending_rows", action="skip")
        return df

    # We process in batches of 50 for resilience and checkpointing
    # If test_limit is provided, we respect it.
    target_process_count = test_limit if test_limit else remaining
    processed_so_far = 0

    log_event(logger, "scholar.enrich.target", rows=target_process_count)

    while processed_so_far < target_process_count:
        batch_size = min(50, target_process_count - processed_so_far)

        # enrich_paper_batch handles internal skipping of already enriched rows
        # based on the 'enriched' column.
        df = enrich_paper_batch(
            df, batch_size=batch_size, allow_paid_proxy=True)

        # Incremental save
        try:
            write_dataframe_artifact(df, output_file, index=False)
            log_event(logger, "checkpoint.saved", source="scholar_enrichment",
                      path=path_name(output_file), rows=len(df))
        except Exception as e:
            log_error(logger, "scholar.enrich.checkpoint_failed",
                      exc=e, path=output_file)

        # Check how many were actually added/updated in this loop
        enriched_mask = df.get("enriched", "").astype(
            str).str.lower() == "true"
        current_enriched = len(df[enriched_mask])
        newly_done = current_enriched - already_enriched

        if newly_done >= target_process_count:
            break

        processed_so_far = newly_done

        # Stop if no more papers can be enriched (remaining count doesn't move)
        if remaining == (total_papers - current_enriched):
            log_warning(logger, "scholar.enrich.no_progress",
                        action="stop", possible_causes="api_limits_or_no_matches")
            break
        remaining = total_papers - current_enriched
        if remaining <= 0:
            break

    enriched_mask = df.get("enriched", "").astype(str).str.lower() == "true"
    log_event(logger, "scholar.enrich.done", enriched_rows=len(
        df[enriched_mask]), total_rows=total_papers)

    return df
