"""
Transform: Paper Enrichment (Micro-batch)
==========================================
Enriches papers with metadata from multiple APIs in priority order:
  Phase 1: Semantic Scholar (FREE) -> Abstract, DOI, TLDR
  Phase 2: OpenAlex (FREE) -> Keywords, Author IDs, DOI
  Phase 3: Local TLDR Generation (Qwen2.5-0.5B) -> TLDR from abstract

Designed for Airflow micro-batch execution with idempotency.
"""
import time
import pandas as pd

from ..extract.semantic_scholar import extract_s2_metadata
from ..extract.openalex import extract_openalex_metadata


# ─── Qwen TLDR Generator (Singleton) ───────────────────────────

_tldr_model = None
_tldr_tokenizer = None

def _load_tldr_model():
    """Load Qwen2.5-0.5B-Instruct once (singleton). CPU-only, ~1.5GB RAM."""
    global _tldr_model, _tldr_tokenizer
    if _tldr_model is not None:
        return _tldr_model, _tldr_tokenizer

    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch

        model_id = "Qwen/Qwen2.5-0.5B-Instruct"
        print(f"🤖 Loading TLDR model: {model_id}...")
        
        _tldr_tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        _tldr_model = AutoModelForCausalLM.from_pretrained(
            model_id, 
            trust_remote_code=True,
            torch_dtype=torch.float32, # CPU-friendly
            device_map="cpu"
        )
        _tldr_model.eval()
        
        print(f"✅ TLDR model loaded ({model_id}, CPU mode)")
        return _tldr_model, _tldr_tokenizer
    except Exception as e:
        print(f"⚠️ Could not load TLDR model: {e}")
        return None, None


def generate_local_tldr(title: str, abstract: str) -> str:
    """
    Generate a one-sentence TLDR from title + abstract using Qwen2.5.
    Returns empty string on failure.
    """
    if not abstract or len(abstract.strip()) < 30:
        return ""

    model, tokenizer = _load_tldr_model()
    if model is None:
        return ""

    try:
        import torch
        # ChatML format for Qwen Instruct models
        prompt = (
            "<|im_start|>system\n"
            "You are an expert academic assistant. Summarize academic abstracts into exactly one concise sentence.<|im_end|>\n"
            "<|im_start|>user\n"
            f"Title: {title}\n"
            f"Abstract: {abstract[:1200]}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
        
        inputs = tokenizer(prompt, return_tensors="pt", max_length=1500, truncation=True)
        inputs = {k: v.to("cpu") for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=100,
                temperature=0.1,
                do_sample=False, # Use greedy for consistency in academic TLDRs
                pad_token_id=tokenizer.eos_token_id
            )
        
        # Extract only the generated part
        gen_tokens = outputs[0][inputs['input_ids'].shape[1]:]
        tldr = tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()
        
        return tldr if len(tldr) > 10 else ""
    except Exception as e:
        print(f"      ⚠️ TLDR generation error: {e}")
        return ""

# ─── Main Enrichment ────────────────────────────────────────────

def enrich_paper_batch(
    df: pd.DataFrame,
    batch_size: int = 50,
    start_idx: int = 0,
) -> pd.DataFrame:
    """
    Enrich a batch of papers with metadata from free APIs + local TLDR.
    Only processes papers that haven't been enriched yet.

    Args:
        df: DataFrame of papers with at least 'Title' column.
        batch_size: Number of papers to process in this batch.
        start_idx: Starting index for this batch.

    Returns:
        Enriched DataFrame (same length, updated in-place).
    """
    # Ensure columns exist
    for col in ["Abstract", "Keywords", "DOI", "TLDR", "Document Type", "Authors", "Author IDs", "enriched"]:
        if col not in df.columns:
            df[col] = ""

    # Filter un-enriched papers
    mask = df["enriched"].astype(str).str.lower() != "true"
    pending_indices = df[mask].index.tolist()

    if start_idx >= len(pending_indices):
        print("   ✅ All papers already enriched!")
        return df

    batch_indices = pending_indices[start_idx:start_idx + batch_size]
    total = len(batch_indices)

    print(f"\n🔧 ENRICH: Processing batch of {total} papers (idx {start_idx}-{start_idx + total})")
    print("=" * 60)

    stats = {"s2": 0, "oa": 0, "abs": 0, "kw": 0, "doi": 0, "tldr": 0, "tldr_local": 0}
    t_start = time.time()

    for count, i in enumerate(batch_indices, 1):
        row = df.loc[i]
        title = str(row.get("Title", "")).strip()
        abstract = str(row.get("Abstract", "")).strip()
        keywords = str(row.get("Keywords", "")).strip()
        doi = str(row.get("DOI", "")).strip()
        tldr = str(row.get("TLDR", "")).strip()
        doc_type = str(row.get("Document Type", "")).strip()
        journal = str(row.get("Journal", "")).strip()
        year = str(row.get("Year", "")).strip()
        authors = str(row.get("Authors", "")).strip()
        author_ids = str(row.get("Author IDs", "")).strip()

        print(f"\n[{count}/{total}] {title[:60]}...")

        time.sleep(0.5)  # Rate limiting

        # ── Phase 1: Semantic Scholar ──
        print(f"   [Phase 1] Semantic Scholar...")
        s2 = extract_s2_metadata(doi=doi if doi else None, title=title)
        if s2:
            stats["s2"] += 1
            if not tldr and s2.get('tldr'):
                tldr = str(s2['tldr'].get('text', '')) if isinstance(s2['tldr'], dict) else str(s2['tldr'])
            if not abstract and s2.get('abstract'):
                abstract = str(s2['abstract'])
            if not doi and s2.get('externalIds', {}).get('DOI'):
                doi = s2['externalIds']['DOI']
            if not year and s2.get('year'):
                year = str(s2['year'])
            if not journal and s2.get('venue'):
                journal = str(s2['venue'])
            if not doc_type and s2.get('publicationTypes'):
                doc_type = ", ".join(s2['publicationTypes'])
        else:
            print(f"      -> MISS: Not found in S2")

        # ── Phase 2: OpenAlex ──
        print(f"   [Phase 2] OpenAlex...")
        oa = extract_openalex_metadata(doi=doi if doi else None, title=title)
        if oa:
            stats["oa"] += 1
            if not keywords and oa.get('keywords'):
                keywords = oa['keywords']
            if not doc_type and oa.get('doc_type'):
                doc_type = oa['doc_type']
            if not year and oa.get('publication_year'):
                year = str(oa['publication_year'])
            if not doi and oa.get('doi'):
                doi = oa['doi']
            if not abstract and oa.get('abstract'):
                abstract = oa['abstract']
            loc = oa.get('primary_location') or {}
            if not journal and loc.get('source'):
                journal = str(loc['source'].get('display_name', ''))
        else:
            print(f"      -> MISS: Not found in OpenAlex")

        # (Phase 2.5 was removed. Author normalization is now handled natively in cleaner.py)

        # ── Phase 3: Local TLDR Generation (Qwen2.5) ──
        if not tldr and abstract and len(abstract) > 30:
            print(f"   [Phase 3] Local TLDR (Qwen2.5-0.5B)...")
            local_tldr = generate_local_tldr(title, abstract)
            if local_tldr:
                tldr = local_tldr
                stats["tldr_local"] += 1
                print(f"      ✨ Generated: {tldr[:60]}...")

        # ── Fallback defaults ──
        if not doc_type:
            doc_type = "Artikel"

        # ── Update DataFrame ──
        df.at[i, "Abstract"] = abstract
        df.at[i, "Keywords"] = keywords
        df.at[i, "DOI"] = doi
        df.at[i, "TLDR"] = tldr
        df.at[i, "Document Type"] = doc_type
        df.at[i, "Journal"] = journal
        df.at[i, "Year"] = year
        df.at[i, "Authors"] = authors
        df.at[i, "Author IDs"] = author_ids
        df.at[i, "enriched"] = "True"

        # Stats
        if abstract: stats["abs"] += 1
        if keywords: stats["kw"] += 1
        if doi: stats["doi"] += 1
        if tldr: stats["tldr"] += 1

        elapsed = time.time() - t_start
        avg = elapsed / count
        eta = ((total - count) * avg) / 60
        print(f"   ✅ [{count}/{total}] ETA: {eta:.1f} min")

    # Final report
    print(f"\n{'=' * 60}")
    print(f"ENRICHMENT BATCH DONE - {total} papers processed")
    print(f"   S2 hits        : {stats['s2']}/{total}")
    print(f"   OA hits        : {stats['oa']}/{total}")
    print(f"   Abstract       : {stats['abs']}/{total}")
    print(f"   Keywords       : {stats['kw']}/{total}")
    print(f"   DOI            : {stats['doi']}/{total}")
    print(f"   TLDR (total)   : {stats['tldr']}/{total}")
    print(f"   TLDR (local)   : {stats['tldr_local']}/{total}")
    print(f"{'=' * 60}")

    return df
