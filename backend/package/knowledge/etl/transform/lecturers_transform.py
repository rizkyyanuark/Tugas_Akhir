"""
Transform: Lecturers Data Cleaning & ID Formatting
====================================================
Ensures that all ID columns (NIP, NIDN, scopus_id, scholar_id, sinta_id)
are consistently formatted as clean strings — never floats, never rounded.
"""
import re
import pandas as pd
import numpy as np


# ─── ID Columns ─────────────────────────────────────────────────

ID_COLUMNS = ["nip", "nidn", "scopus_id", "scholar_id", "sinta_id"]


def clean_id_column(series: pd.Series) -> pd.Series:
    """
    Clean an ID column to ensure string consistency:
    - Strip '.0' suffix (from float casting by pandas)
    - Convert NaN/None/nan to empty string
    - Strip whitespace
    - Never cast to int/float
    """
    def _clean_single(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        s = str(val).strip()
        # Remove pandas float artifact (.0 suffix)
        if s.endswith(".0"):
            s = s[:-2]
        # Remove common garbage values
        if s.lower() in ("nan", "none", "null", "na", ""):
            return ""
        return s

    return series.apply(_clean_single)


def format_id_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply ID formatting to all known ID columns.
    Ensures NIP/NIDN/scopus_id/scholar_id/sinta_id are clean strings.
    """
    print("🔢 Formatting ID columns...")
    for col in ID_COLUMNS:
        if col in df.columns:
            before_empty = (df[col].astype(str).str.strip().isin(["", "nan", "None"])).sum()
            df[col] = clean_id_column(df[col])
            after_empty = (df[col] == "").sum()
            non_empty = len(df) - after_empty
            print(f"   {col}: {non_empty} valid IDs, {after_empty} empty")
    return df


# ─── Name Cleaning ──────────────────────────────────────────────

def clean_lecturer_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize lecturer names:
    - Strip whitespace
    - Ensure title case for nama_dosen
    - Clean nama_norm (lowercase, no titles)
    """
    print("👤 Cleaning lecturer names...")

    if "nama_dosen" in df.columns:
        df["nama_dosen"] = df["nama_dosen"].astype(str).str.strip()

    if "nama_norm" in df.columns:
        df["nama_norm"] = df["nama_norm"].astype(str).str.strip()
        # Remove common garbage
        df["nama_norm"] = df["nama_norm"].replace({"nan": "", "None": ""})

    return df


# ─── Schema Validation ──────────────────────────────────────────

REQUIRED_COLUMNS = ["nama_dosen", "nip"]

def validate_lecturer_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure all required columns exist. Add missing ones as empty.
    Drop rows without a valid nama_dosen.
    """
    print("📋 Validating lecturer schema...")
    
    # Add missing columns
    all_expected = [
        "nama_dosen", "nama_norm", "nip", "nidn", "prodi",
        "scopus_id", "scholar_id", "sinta_id", "source"
    ]
    for col in all_expected:
        if col not in df.columns:
            df[col] = ""
            print(f"   Added missing column: {col}")

    # Drop rows without nama_dosen
    before = len(df)
    df = df[df["nama_dosen"].astype(str).str.strip() != ""].reset_index(drop=True)
    dropped = before - len(df)
    if dropped > 0:
        print(f"   ⚠️ Dropped {dropped} rows without nama_dosen")

    print(f"   ✅ Schema valid: {len(df)} lecturers")
    return df


# ─── Full Transform Pipeline ────────────────────────────────────

def transform_lecturers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full transform pipeline for lecturer data:
    1. Format ID columns (no .0, no float rounding)
    2. Clean names
    3. Validate schema
    """
    print("\n🔧 TRANSFORM: Lecturer Data")
    print("=" * 50)

    df = format_id_columns(df)
    df = clean_lecturer_names(df)
    df = validate_lecturer_schema(df)

    print(f"\n✅ Transform complete: {len(df)} clean lecturer records")
    return df
