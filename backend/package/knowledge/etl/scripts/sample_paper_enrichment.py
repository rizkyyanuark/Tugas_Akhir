from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd


DEFAULT_SOURCE = Path("data/papers_sample.csv")
DEFAULT_OUT_DIR = Path("data/manual_tests/groq_5_paper_test")


def _load_env_file(path: Path) -> None:
    """Load a local .env file without printing secret values."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map common paper columns into the Scholar enrichment schema."""
    rename_map = {
        "title": "Title",
        "abstract": "Abstract",
        "keywords": "Keywords",
        "year": "Year",
        "journal": "Journal",
        "authors": "Authors",
        "author_ids": "Author IDs",
        "doi": "DOI",
        "link": "Link",
    }
    existing_map = {src: dst for src, dst in rename_map.items() if src in df.columns}
    normalized = df.rename(columns=existing_map).copy()

    for column in [
        "Authors",
        "Author IDs",
        "Title",
        "Year",
        "Journal",
        "Link",
        "Abstract",
        "Keywords",
        "Document Type",
        "DOI",
        "TLDR",
        "citation_id",
        "scholar_id",
        "lecturer_name",
        "source",
        "enriched",
    ]:
        if column not in normalized.columns:
            normalized[column] = ""

    return normalized


def _prepare_sample(source: Path, limit: int, force_regenerate: bool) -> pd.DataFrame:
    from knowledge.etl.utils.storage import read_dataframe_csv

    df = read_dataframe_csv(source, dtype=str).fillna("")
    df = _normalize_columns(df)
    df = df[df["Title"].astype(str).str.strip().ne("")].head(limit).copy()

    if df.empty:
        raise SystemExit(f"No titled papers found in {source}")

    if force_regenerate:
        df["TLDR"] = ""
        df["enriched"] = ""

    df["source"] = df["source"].replace("", "manual_sample")
    return df


def _print_preview(df: pd.DataFrame) -> None:
    print("\n=== Enrichment preview ===")
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        title = str(row.get("Title", "")).strip().replace("\n", " ")
        tldr = str(row.get("TLDR", "")).strip().replace("\n", " ")
        abstract_len = len(str(row.get("Abstract", "")).strip())
        keywords = str(row.get("Keywords", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        enriched = str(row.get("enriched", "")).strip()

        print(f"\n[{i}] {title}")
        print(
            "  "
            f"abstract_len={abstract_len} "
            f"keywords={'yes' if keywords else 'no'} "
            f"doi={'yes' if doi else 'no'} "
            f"enriched={enriched}"
        )
        print(f"  TLDR: {tldr}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a safe manual paper enrichment/TLDR smoke test."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not clear existing TLDR/enriched flags before processing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _load_env_file(args.env_file)

    from knowledge.etl.services.unesa_papers import run_scholar_enrichment
    from knowledge.etl.utils.storage import write_dataframe_csv

    args.out_dir.mkdir(parents=True, exist_ok=True)
    input_csv = args.out_dir / f"input_{args.limit}_papers.csv"
    output_csv = args.out_dir / f"enriched_{args.limit}_papers.csv"

    sample_df = _prepare_sample(
        source=args.source,
        limit=args.limit,
        force_regenerate=not args.keep_existing,
    )
    write_dataframe_csv(sample_df, input_csv, index=False)

    enriched_df = run_scholar_enrichment(
        input_csv=input_csv,
        output_csv=output_csv,
        test_limit=len(sample_df),
    )

    print(f"Input CSV: {input_csv}")
    print(f"Output CSV: {output_csv}")
    print(f"Rows processed: {len(enriched_df)}")
    _print_preview(enriched_df.head(len(sample_df)))


if __name__ == "__main__":
    main()
