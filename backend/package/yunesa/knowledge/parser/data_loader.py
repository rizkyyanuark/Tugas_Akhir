"""
data_loader.py — UNESA Academic Data Loaders
=============================================
Data loaders for Supabase, Self-Hosted PostgreSQL, and local CSV samples.
"""

from __future__ import annotations

import os
from pathlib import Path
import pandas as pd

from yunesa.knowledge.utils.text_processing import safe_str, stable_id


def fetch_postgres_sample(sample_size: int = 50) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read sample data from Self-Hosted PostgreSQL (postgres-prod)."""
    import psycopg

    host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST") or "postgres-prod"
    port = os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432"
    db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE") or "tugas_akhir"
    user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or "71509325"

    conn_str = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            limit_clause = f" LIMIT {max(sample_size * 3, sample_size)}" if sample_size > 0 else ""
            cur.execute(
                f"SELECT paper_id, title, abstract, tldr, keywords, year, journal, document_type, authors, author_ids, doi, link FROM papers ORDER BY year DESC NULLS LAST{limit_clause};"
            )
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
            papers_df = pd.DataFrame(rows, columns=cols)

            cur.execute("SELECT nip, nama_dosen, nama_norm, nidn, prodi, scopus_id, scholar_id, sinta_id FROM lecturers;")
            l_rows = cur.fetchall()
            l_cols = [desc[0] for desc in cur.description]
            lecturers_df = pd.DataFrame(l_rows, columns=l_cols)

    if not papers_df.empty:
        papers_df = papers_df[
            papers_df["title"].map(lambda value: bool(safe_str(value)))
            & (
                papers_df["abstract"].map(lambda value: len(safe_str(value)) > 20)
                | papers_df["tldr"].map(lambda value: len(safe_str(value)) > 20)
            )
        ]
        if sample_size > 0:
            papers_df = papers_df.head(sample_size).copy()

    links = []
    if not papers_df.empty:
        for _, row in papers_df.iterrows():
            pid = row.get("paper_id")
            a_ids = str(row.get("author_ids") or "")
            if pid and a_ids:
                for aid in a_ids.replace(";", ",").split(","):
                    aid_clean = aid.strip()
                    if aid_clean:
                        links.append({"paper_id": pid, "nip": aid_clean})
    links_df = pd.DataFrame(links)
    return papers_df.reset_index(drop=True), lecturers_df.reset_index(drop=True), links_df.reset_index(drop=True)


def fetch_supabase_sample(sample_size: int = 50) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read sample data from Supabase."""
    try:
        from supabase import create_client
    except ImportError as exc:
        raise ImportError("supabase package is required for fetch_supabase_sample().") from exc

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY first.")

    client = create_client(url, key)

    paper_cols_list = [
        "paper_id",
        "title",
        "abstract",
        "tldr",
        "keywords",
        "year",
        "journal",
        "document_type",
        "authors",
        "author_ids",
        "doi",
        "link",
    ]
    paper_cols = ",".join(paper_cols_list)
    lecturer_cols_list = ["nip", "nama_dosen", "nama_norm", "nidn", "prodi", "scopus_id", "scholar_id", "sinta_id"]
    lecturer_cols = ",".join(lecturer_cols_list)

    # ── 1. Fetch Papers via Paginated Batching (1000 items/page) ──
    all_papers = []
    page_size = 1000
    target_count = max(sample_size * 3, sample_size) if sample_size > 0 else 100000
    offset = 0

    while offset < target_count:
        chunk_limit = min(page_size, target_count - offset)
        resp = (
            client.table("papers")
            .select(paper_cols)
            .order("year", desc=True)
            .range(offset, offset + chunk_limit - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        all_papers.extend(batch)
        offset += len(batch)
        if len(batch) < chunk_limit:
            break

    papers_df = pd.DataFrame(all_papers) if all_papers else pd.DataFrame(columns=paper_cols_list)

    if not papers_df.empty and "title" in papers_df.columns:
        for col in paper_cols_list:
            if col not in papers_df.columns:
                papers_df[col] = None

        papers_df = papers_df[
            papers_df["title"].map(lambda value: bool(safe_str(value)))
            & (
                papers_df["abstract"].fillna("").map(lambda value: len(safe_str(value)) > 20)
                | papers_df["tldr"].fillna("").map(lambda value: len(safe_str(value)) > 20)
            )
        ]
        if sample_size > 0:
            papers_df = papers_df.head(sample_size)

    # ── 2. Fetch Lecturers ──
    lecturer_response = client.table("lecturers").select(lecturer_cols).limit(5000).execute()
    raw_lecturers = lecturer_response.data or []
    lecturers_df = pd.DataFrame(raw_lecturers) if raw_lecturers else pd.DataFrame(columns=lecturer_cols_list)

    # ── 3. Fetch Links via Paginated Batching ──
    all_links = []
    offset = 0
    link_target = max(sample_size * 20, 200) if sample_size > 0 else 200000

    while offset < link_target:
        chunk_limit = min(page_size, link_target - offset)
        link_resp = (
            client.table("paper_lecturers")
            .select("paper_id,nip")
            .range(offset, offset + chunk_limit - 1)
            .execute()
        )
        batch = link_resp.data or []
        if not batch:
            break
        all_links.extend(batch)
        offset += len(batch)
        if len(batch) < chunk_limit:
            break

    links_df = pd.DataFrame(all_links) if all_links else pd.DataFrame(columns=["paper_id", "nip"])

    if not papers_df.empty and not links_df.empty:
        links_df = links_df[links_df["paper_id"].isin(set(papers_df["paper_id"].astype(str)))]

    return papers_df, lecturers_df, links_df


def load_local_csv_sample(base_dir: Path, sample_size: int = 50) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fallback loader for offline notebook runs."""
    lecturer_path = base_dir / "dosen_infokom_final.csv"
    paper_candidates = [
        base_dir / "dosen_papers_scopus_final.csv",
        base_dir / "dosen_papers_scopus.csv",
        base_dir / "dosen_papers_scholar.csv",
    ]

    lecturers_df = pd.read_csv(lecturer_path, dtype=str).fillna("") if lecturer_path.exists() else pd.DataFrame()

    frames = []
    for path in paper_candidates:
        if path.exists():
            frames.append(pd.read_csv(path, dtype=str).fillna(""))

    papers_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not papers_df.empty:
        rename_map = {
            "Title": "title",
            "Abstract": "abstract",
            "Keywords": "keywords",
            "Year": "year",
            "Journal": "journal",
            "Authors": "authors",
            "Author IDs": "author_ids",
            "DOI": "doi",
            "Link": "link",
            "Document Type": "document_type",
        }
        papers_df = papers_df.rename(columns={k: v for k, v in rename_map.items() if k in papers_df.columns})
        if "paper_id" not in papers_df.columns:
            papers_df["paper_id"] = papers_df["title"].map(lambda title: stable_id("paper", title))
        papers_df = papers_df.head(sample_size)

    return papers_df, lecturers_df, pd.DataFrame(columns=["paper_id", "nip"])
