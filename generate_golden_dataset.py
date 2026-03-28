"""
=============================================================================
GOLDEN DATASET GENERATOR
Ontology-Aware TLDR Training Pipeline — Phase 0
=============================================================================
Script ini membaca abstrak paper dari CSV lokal (scraping results) dan 
Supabase DB, lalu men-generate TLDR 2-kalimat bahasa Inggris menggunakan
LLM teacher (Llama-4-Scout-17B via Groq) untuk dijadikan data pelatihan
model Qwen2.5-0.5B.

Output: JSONL file siap pakai untuk SFT training di Kaggle.
=============================================================================
"""

import os
import sys
import json
import time
import hashlib
import pandas as pd
from pathlib import Path
from groq import Groq

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "***REMOVED***")
TEACHER_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Paths
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "golden_dataset"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "golden_tldr_dataset.jsonl"

# Min abstract length to be considered valid
MIN_ABSTRACT_LENGTH = 50

client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPTS (Sama persis dengan enricher.py production)
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT_TLDR = """You are an AI assistant specializing in strict academic data extraction.
Your Task: Read the following journal abstract and summarize it into EXACTLY 2 SENTENCES in ENGLISH that are very dense and specific.

ONTOLOGY SCHEMA RULES:
[Problem], [Task], [Field], [Method], [Model], [Innovation], [Dataset], [Tool], [Metric].

STRUCTURE (MANDATORY):
Sentence 1: Background & Approach (You MUST include Problem/Task, Field, and Method).
Sentence 2: Experiments & Results (You MUST explicitly write out the Metric, Tool, and Dataset used).

EXAMPLE 1 (Algorithm Research):
Abstract: "Penelitian mendeteksi hoaks pada Twitter menggunakan algoritma BERT. Kami menggunakan dataset ID-Hoax dan mencapai akurasi 95%."
Output: This research addresses hoax detection within the Twitter social media domain using the BERT algorithm. Experiments were conducted on the ID-Hoax dataset and achieved an accuracy of 95%.

EXAMPLE 2 (System/App Development):
Abstract: "Penelitian ini mengembangkan bot telegram di UNESA. Hasil menunjukkan bot mampu memberi respons realtime tanpa bug dengan kecepatan 1050 ms hingga 1680 ms."
Output: This study develops a Telegram bot system with webhook integration for sexual violence reporting services at Universitas Negeri Surabaya. Performance measurement results indicated a fast real-time response capability ranging from 1050 ms to 1680 ms without system bugs.

CRITICAL RULES:
- You are FORBIDDEN from outputting only 1 sentence. YOU MUST OUTPUT EXACTLY 2 SENTENCES.
- If there are numbers, percentages, or ms (milliseconds) in the abstract, you MUST include them in Sentence 2 as the [Metric].
- NO pronouns like "this method".
- THE OUTPUT MUST BE IN ENGLISH.
- DO NOT output any introductory text, conversational fillers, or phrases like 'Here is the summary'. START IMMEDIATELY with the first sentence."""


# ─────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────
def detect_language(text: str) -> str:
    """Simple heuristic: if >3 Indonesian keywords found, label as 'id'."""
    id_keywords = ['penelitian', 'bertujuan', 'menggunakan', 'metode', 'hasil',
                   'menunjukkan', 'dalam', 'dengan', 'untuk', 'pada', 'sistem',
                   'berdasarkan', 'pengembangan', 'analisis', 'terhadap']
    text_lower = text.lower()
    count = sum(1 for w in id_keywords if w in text_lower)
    return "id" if count >= 3 else "en"


def load_abstracts_from_csv() -> list[dict]:
    """Load abstracts from all available local CSV files."""
    csv_files = [
        BASE_DIR / "notebooks" / "scraping" / "file_tabulars" / "dosen_papers_scholar_colab.csv",
    ]
    
    records = []
    seen_titles = set()
    
    for csv_path in csv_files:
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path)
            if 'Abstract' not in df.columns:
                continue
            
            for _, row in df.iterrows():
                abstract = str(row.get('Abstract', '')).strip()
                title = str(row.get('Title', '')).strip()
                
                if len(abstract) < MIN_ABSTRACT_LENGTH or abstract.lower() == 'nan':
                    continue
                if title.lower() in seen_titles:
                    continue
                
                seen_titles.add(title.lower())
                records.append({
                    "abstract_text": abstract,
                    "title": title,
                    "abstract_lang": detect_language(abstract),
                    "source": "infokom_unesa"
                })
        except Exception as e:
            print(f"⚠️ Error reading {csv_path.name}: {e}")
    
    return records


def load_abstracts_from_supabase() -> list[dict]:
    """Load abstracts from Supabase DB."""
    creds_path = BASE_DIR / "notebooks" / "scraping" / "credentials_new.json"
    if not creds_path.exists():
        print("ℹ️ No Supabase credentials found, skipping...")
        return []
    
    try:
        import requests
        creds = json.load(open(creds_path))
        sb_url = creds['supabase']['url']
        sb_key = creds['supabase']['key']
        
        headers = {"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
        
        all_papers = []
        offset = 0
        batch_size = 1000
        
        while True:
            r = requests.get(
                f"{sb_url}/rest/v1/papers",
                headers=headers,
                params={
                    "select": "paper_id,title,abstract",
                    "abstract": "not.is.null",
                    "offset": offset,
                    "limit": batch_size
                }
            )
            data = r.json()
            if not data:
                break
            all_papers.extend(data)
            offset += batch_size
            if len(data) < batch_size:
                break
        
        records = []
        for p in all_papers:
            abstract = (p.get('abstract') or '').strip()
            title = (p.get('title') or '').strip()
            if len(abstract) >= MIN_ABSTRACT_LENGTH:
                records.append({
                    "abstract_text": abstract,
                    "title": title,
                    "abstract_lang": detect_language(abstract),
                    "source": "infokom_unesa"
                })
        
        return records
    except Exception as e:
        print(f"⚠️ Supabase load error: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# TLDR GENERATION VIA TEACHER MODEL
# ─────────────────────────────────────────────────────────────
def generate_tldr(abstract: str) -> str:
    """Generate ontology-aware 2-sentence TLDR using Llama-4-Scout."""
    try:
        completion = client.chat.completions.create(
            model=TEACHER_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_TLDR},
                {"role": "user", "content": f"ORIGINAL ABSTRACT:\n{abstract}\n\nOUTPUT 2-SENTENCE TL;DR IN ENGLISH:"}
            ],
            temperature=0.0,
            max_tokens=256,
            stream=False
        )
        
        tldr = completion.choices[0].message.content.strip()
        
        # Post-processing: remove intro phrases
        remove_prefixes = [
            "Here is the 2-sentence summary:",
            "Here is the summary:",
            "Here are the two sentences:",
            "Summary:",
        ]
        for prefix in remove_prefixes:
            if tldr.lower().startswith(prefix.lower()):
                tldr = tldr[len(prefix):].strip()
        
        return tldr
    except Exception as e:
        print(f"      ⚠️ Error: {e}")
        return ""


def validate_tldr(tldr: str) -> dict:
    """Check if TLDR meets ontology quality criteria."""
    sentences = [s.strip() for s in tldr.split('.') if s.strip()]
    is_2_sentences = len(sentences) == 2
    
    tldr_lower = tldr.lower()
    has_problem = any(w in tldr_lower for w in ['address', 'tackle', 'develop', 'implement', 'propose', 'design', 'problem', 'challenge'])
    has_method = any(w in tldr_lower for w in ['method', 'algorithm', 'model', 'approach', 'technique', 'framework', 'system', 'using', 'employ'])
    has_dataset = any(w in tldr_lower for w in ['dataset', 'data', 'sample', 'respondent', 'participant', 'corpus', 'survey'])
    has_results = any(w in tldr_lower for w in ['achiev', 'result', 'performance', 'accuracy', 'f1', 'recall', 'precision', '%', 'score', 'metric', 'ms ', 'millisecond'])
    
    return {
        "is_2_sentences": is_2_sentences,
        "has_problem": has_problem,
        "has_method": has_method, 
        "has_dataset": has_dataset,
        "has_results": has_results,
    }


# ─────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────
def main():
    print("="*70)
    print("🚀 GOLDEN DATASET GENERATOR — Ontology-Aware TLDR")
    print("="*70)
    
    # 1. Load all abstracts
    print("\n📂 Loading abstracts from all sources...")
    csv_records = load_abstracts_from_csv()
    print(f"   CSV: {len(csv_records)} records")
    
    sb_records = load_abstracts_from_supabase()
    print(f"   Supabase: {len(sb_records)} records")
    
    # Deduplicate by title
    all_records = []
    seen = set()
    for r in csv_records + sb_records:
        key = r['title'].lower().strip()
        if key not in seen:
            seen.add(key)
            all_records.append(r)
    
    print(f"\n   📊 Total unique abstracts: {len(all_records)}")
    id_count = sum(1 for r in all_records if r['abstract_lang'] == 'id')
    print(f"   🇮🇩 Indonesian: {id_count}")
    print(f"   🇬🇧 English: {len(all_records) - id_count}")
    
    if not all_records:
        print("\n⚠️ No abstracts found! Please run the scraping pipeline first.")
        return
    
    # 2. Load existing progress (resume support)
    existing_ids = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    existing_ids.add(rec.get('id', ''))
                except:
                    pass
        print(f"\n♻️ Resuming: {len(existing_ids)} already generated, skipping...")
    
    # 3. Generate TLDRs
    print(f"\n🤖 Generating TLDRs with [{TEACHER_MODEL}]...")
    print(f"   Rate limit protection: 3s delay per request")
    print("-"*70)
    
    success = 0
    failed = 0
    quality_stats = {"2_sent": 0, "problem": 0, "method": 0, "dataset": 0, "results": 0}
    
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f_out:
        for i, record in enumerate(all_records):
            # Create unique ID
            rec_id = hashlib.md5(record['title'].lower().encode()).hexdigest()[:12]
            
            if rec_id in existing_ids:
                continue
            
            abstract = record['abstract_text']
            print(f"\n[{i+1}/{len(all_records)}] {record['title'][:60]}...")
            
            # Generate TLDR
            tldr = generate_tldr(abstract)
            
            if not tldr or len(tldr) < 20:
                print(f"   ❌ Failed (empty/too short)")
                failed += 1
                time.sleep(3)
                continue
            
            # Validate quality
            quality = validate_tldr(tldr)
            
            # Build golden record
            golden_record = {
                "id": rec_id,
                "abstract_lang": record['abstract_lang'],
                "abstract_text": abstract,
                "tldr_text": tldr,
                "source": record['source'],
                "has_problem": quality['has_problem'],
                "has_method": quality['has_method'],
                "has_dataset": quality['has_dataset'],
                "has_results": quality['has_results'],
                "is_2_sentences": quality['is_2_sentences'],
                "teacher_model": TEACHER_MODEL,
            }
            
            # Write to JSONL
            f_out.write(json.dumps(golden_record, ensure_ascii=False) + "\n")
            f_out.flush()
            
            # Update stats
            success += 1
            for k in quality_stats:
                if k == "2_sent":
                    quality_stats[k] += int(quality['is_2_sentences'])
                elif k == "problem":
                    quality_stats[k] += int(quality['has_problem'])
                elif k == "method":
                    quality_stats[k] += int(quality['has_method'])
                elif k == "dataset":
                    quality_stats[k] += int(quality['has_dataset'])
                elif k == "results":
                    quality_stats[k] += int(quality['has_results'])
            
            print(f"   ✅ TLDR: {tldr[:100]}...")
            slots = sum([quality['has_problem'], quality['has_method'], quality['has_dataset'], quality['has_results']])
            print(f"   📊 Ontology slots: {slots}/4 | 2-sent: {'✅' if quality['is_2_sentences'] else '❌'}")
            
            # Rate limit cooldown
            time.sleep(3)
    
    # 4. Final Report
    total = success + failed
    print("\n" + "="*70)
    print("📊 GOLDEN DATASET GENERATION REPORT")
    print("="*70)
    print(f"Total processed:    {total}")
    print(f"✅ Success:         {success}")
    print(f"❌ Failed:          {failed}")
    if success > 0:
        print(f"\n--- Ontology Quality (out of {success}) ---")
        print(f"2-Sentence format:  {quality_stats['2_sent']}/{success} ({quality_stats['2_sent']/success*100:.1f}%)")
        print(f"Has Problem/Task:   {quality_stats['problem']}/{success} ({quality_stats['problem']/success*100:.1f}%)")
        print(f"Has Method/Model:   {quality_stats['method']}/{success} ({quality_stats['method']/success*100:.1f}%)")
        print(f"Has Dataset:        {quality_stats['dataset']}/{success} ({quality_stats['dataset']/success*100:.1f}%)")
        print(f"Has Results/Metric: {quality_stats['results']}/{success} ({quality_stats['results']/success*100:.1f}%)")
    print(f"\n💾 Output saved to: {OUTPUT_FILE}")
    print("="*70)


if __name__ == "__main__":
    main()
