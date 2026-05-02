# %% [markdown]
# # 🧠 Knowledge Graph Construction Pipeline
# 
# **UNESA Academic Knowledge Graph — Colab/Kaggle Edition**
# 
# Pipeline ini membangun Knowledge Graph dari data paper akademik dan dosen UNESA.
# 
# | Komponen | Teknologi |
# |---|---|
# | LLM | Qwen 2.5 3B Instruct (Local, GPU T4) |
# | Graph DB | Neo4j AuraDB |
# | Vector DB | Zilliz Cloud (Managed Milvus) |
# | NER | GLiNER + spaCy |
# | Data Source | Supabase |
# 
# ---

# %% [markdown]
# ## Cell 1: 📦 Install Dependencies

# %%
!pip install -q neo4j supabase requests gliner spacy pandas sentence-transformers pymilvus transformers accelerate bitsandbytes
!python -m spacy download en_core_web_sm
print("✅ All dependencies installed!")

# %% [markdown]
# ## Cell 2: 🔑 Configuration & API Keys

# %%
# ══════════════════════════════════════════════════════════════
# CONFIGURATION — Env-first (Kaggle/Colab Secrets friendly)
# ══════════════════════════════════════════════════════════════

import os
import torch

def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")

# ── Supabase ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://wfjzdhaaldwyiajbyzln.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_CL-gD_LAwdwrsSegQbBvKQ_yG6hQpAC")

# ── Neo4j AuraDB ──
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://87eb5ce1.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", os.getenv("NEO4J_USERNAME", "87eb5ce1"))
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "ujbXXlO2LGXirf-IKYlf29YfJG_2UrLj241-2zYn5gg")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "87eb5ce1")

# ── Zilliz Cloud (Managed Milvus) ──
ZILLIZ_URI = os.getenv("ZILLIZ_URI", "https://in03-ddc8f8adef03a1f.serverless.gcp-us-west1.cloud.zilliz.com")
ZILLIZ_TOKEN = os.getenv("ZILLIZ_TOKEN", "db_ddc8f8adef03a1f:Qj5{K[83~m!<P2WF")
ENABLE_ZILLIZ = _as_bool("ENABLE_ZILLIZ", True)

# ── Local LLM (GPU T4 friendly) ──
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct")
LOCAL_LLM_USE_4BIT = _as_bool("LOCAL_LLM_USE_4BIT", True)
LOCAL_LLM_MAX_NEW_TOKENS = int(os.getenv("LOCAL_LLM_MAX_NEW_TOKENS", "512"))
LOCAL_LLM_TEMPERATURE = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.0"))
LOCAL_LLM_TOP_P = float(os.getenv("LOCAL_LLM_TOP_P", "0.9"))
LOCAL_LLM_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ── Pipeline Settings ──
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "80"))
GLINER_THRESHOLD = float(os.getenv("GLINER_THRESHOLD", "0.15"))
GLINER_MODEL_NAME = os.getenv("GLINER_MODEL_NAME", "urchade/gliner_large-v2.1")
SPACY_MODEL_NAME = os.getenv("SPACY_MODEL_NAME", "en_core_web_lg")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))  # all-MiniLM-L6-v2

# ── Database Mode ──
# True  = Hapus semua data Neo4j dulu, lalu ingest fresh
# False = Append ke data yang sudah ada (default)
CLEAR_NEO4J_BEFORE_INGEST = _as_bool("CLEAR_NEO4J_BEFORE_INGEST", False)

missing = []
for key_name, key_val in {
    "SUPABASE_KEY": SUPABASE_KEY,
    "NEO4J_PASSWORD": NEO4J_PASSWORD,
    "ZILLIZ_TOKEN": ZILLIZ_TOKEN if ENABLE_ZILLIZ else "ok",
}.items():
    if not key_val:
        missing.append(key_name)

print("✅ Configuration loaded!")
print(f"   Device: {LOCAL_LLM_DEVICE}")
print(f"   Local LLM: {LOCAL_LLM_MODEL} (4bit={LOCAL_LLM_USE_4BIT})")
print(f"   Neo4j: {NEO4J_URI} (db={NEO4J_DATABASE}, user={NEO4J_USER})")
print(f"   Zilliz: {'Enabled' if ENABLE_ZILLIZ else 'Disabled'}")
print(f"   Mode: {'CLEAR + INGEST' if CLEAR_NEO4J_BEFORE_INGEST else 'APPEND'}")
if missing:
    print(f"⚠️ Missing secrets: {', '.join(missing)}")
    print("   Set via Kaggle/Colab secrets or environment variables before running ingestion cells.")

# %% [markdown]
# ## Cell 3: 🛠️ Utility Functions & Ontology

# %%
# ══════════════════════════════════════════════════════════════
# UTILITIES & ONTOLOGY
# Ported from: utils.py, ontology.py
# ══════════════════════════════════════════════════════════════

import hashlib
import re
import json
import time
import logging
from collections import OrderedDict, defaultdict
from typing import Dict, List, Optional, Tuple, Set, Any

import spacy
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("KG_Pipeline")

# ── Load spaCy ──
logger.info(f"Loading spaCy model: {SPACY_MODEL_NAME}...")
try:
    nlp = spacy.load(SPACY_MODEL_NAME)
except OSError:
    spacy.cli.download(SPACY_MODEL_NAME)
    nlp = spacy.load(SPACY_MODEL_NAME)
logger.info(f"✅ spaCy model loaded: {SPACY_MODEL_NAME}")


# ── Ontology ──
ONTOLOGY = {
    "node_types": {
        "Dosen":        {"description": "Internal UNESA faculty member"},
        "Paper":        {"description": "Research publication"},
        "ProgramStudi": {"description": "Study program / department"},
        "Journal":      {"description": "Publication venue"},
        "Year":         {"description": "Publication year"},
        "Keyword":      {"description": "Author-assigned keyword"},
        "Method":       {"description": "Research method or algorithm"},
        "Model":        {"description": "ML/AI model architecture"},
        "Metric":       {"description": "Evaluation metric"},
        "Dataset":      {"description": "Dataset used in study"},
        "Problem":      {"description": "Research problem addressed"},
        "Task":         {"description": "Computational/research task"},
        "Field":        {"description": "Research domain/field"},
        "Tool":         {"description": "Software tool or framework"},
        "Innovation":   {"description": "Novel contribution"},
    },
    "ner_label_map": {
        "method": "Method", "algorithm": "Method", "technique": "Method",
        "research method": "Method", "model": "Model", "metric": "Metric",
        "evaluation metric": "Metric", "dataset": "Dataset", "problem": "Problem",
        "task": "Task", "field": "Field", "scientific concept": "Field",
        "tool": "Tool", "framework": "Tool", "software": "Tool",
        "platform": "Tool", "technology": "Tool", "programming language": "Tool",
        "innovation": "Innovation", "results": "Innovation",
    },
}

_STRUCTURAL_LABELS = {"Dosen", "Paper", "ProgramStudi", "Journal", "Year", "Keyword"}

def get_valid_semantic_labels() -> Set[str]:
    return set(ONTOLOGY["node_types"].keys()) - _STRUCTURAL_LABELS

def map_ner_label(raw_label: str) -> str:
    raw_label = str(raw_label)
    mapped = ONTOLOGY["ner_label_map"].get(raw_label.lower())
    if mapped:
        return mapped
    cap = raw_label.capitalize()
    if cap in ONTOLOGY["node_types"]:
        return cap
    return "Field"

def get_all_labels() -> list:
    return list(ONTOLOGY["node_types"].keys())


# ── Utility Functions ──
def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]

def normalize_text(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", str(text).lower().strip())
    return re.sub(r"\s+", " ", text).strip()

def make_lemma_key(text: str) -> str:
    doc = nlp(str(text).strip())
    parts = []
    for tok in doc:
        pos = "NOUN" if tok.pos_ in ("PROPN", "NOUN") else tok.pos_
        if pos in ("NOUN", "ADJ", "VERB"):
            parts.append(f"{pos}.{tok.lemma_.lower()}")
    return " ".join(parts) if parts else normalize_text(text)

def safe_str(value, default: str = "") -> str:
    s = str(value).strip()
    if s.lower() in ("nan", "none", ""):
        return default
    return s

def truncate(text: str, max_len: int = 2000) -> str:
    return text[:max_len] if len(text) > max_len else text

print("✅ Utilities & Ontology loaded!")
print(f"   Semantic labels: {get_valid_semantic_labels()}")

# %% [markdown]
# ## Cell 4: 🤖 Local LLM Client (Qwen 2.5 3B)

# %%
# ══════════════════════════════════════════════════════════════
# Local LLM Client (GPU T4 optimized, no external API)
# Runs fully local (no external LLM API calls)
# ══════════════════════════════════════════════════════════════

import json
import re
import time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

class LocalLLMClient:
    """Local HF model client with JSON extraction, retry, and optional 4-bit quantization."""

    def __init__(self, model=None, max_retries=2):
        self.model_name = model or LOCAL_LLM_MODEL
        self.max_retries = max_retries
        self.max_new_tokens = LOCAL_LLM_MAX_NEW_TOKENS
        self.temperature = LOCAL_LLM_TEMPERATURE
        self.top_p = LOCAL_LLM_TOP_P
        self._call_count = 0
        self._error_count = 0

        model_kwargs = {"trust_remote_code": True}
        if torch.cuda.is_available():
            model_kwargs["device_map"] = "auto"
            if LOCAL_LLM_USE_4BIT:
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                )
            else:
                model_kwargs["torch_dtype"] = torch.float16
        else:
            model_kwargs["torch_dtype"] = torch.float32

        logger.info(f"Loading local LLM: {self.model_name} (device={LOCAL_LLM_DEVICE})")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_name, **model_kwargs)

        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        logger.info("✅ Local LLM loaded")

    @property
    def stats(self):
        return {"llm_calls": self._call_count, "llm_errors": self._error_count, "model": self.model_name}

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        # fallback: ambil blok JSON pertama
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}
        return {}

    def call(self, prompt: str, temperature: float = None) -> Dict[str, Any]:
        temp = self.temperature if temperature is None else temperature
        messages = [
            {
                "role": "system",
                "content": "You are an extraction assistant. Always return a single valid JSON object only, without markdown fences.",
            },
            {"role": "user", "content": prompt},
        ]

        for attempt in range(1, self.max_retries + 1):
            try:
                self._call_count += 1
                input_text = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                inputs = self.tokenizer(input_text, return_tensors="pt")
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

                do_sample = temp > 0
                gen_kwargs = {
                    "max_new_tokens": self.max_new_tokens,
                    "do_sample": do_sample,
                    "top_p": self.top_p,
                    "pad_token_id": self.tokenizer.eos_token_id,
                }
                if do_sample:
                    gen_kwargs["temperature"] = max(0.05, temp)

                with torch.no_grad():
                    output_ids = self.model.generate(**inputs, **gen_kwargs)

                new_tokens = output_ids[0][inputs["input_ids"].shape[-1]:]
                raw = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
                parsed = self._extract_json(raw)
                if parsed:
                    return parsed

                logger.warning(f"Local LLM returned non-JSON output (attempt {attempt}): {raw[:160]}")
                self._error_count += 1
                time.sleep(1.0)
            except Exception as e:
                logger.warning(f"Local LLM error (attempt {attempt}): {type(e).__name__}: {e}")
                self._error_count += 1
                time.sleep(1.5)

        return {}

    def call_with_delay(self, prompt: str, delay: float = 0.4, **kwargs) -> Dict[str, Any]:
        result = self.call(prompt, **kwargs)
        time.sleep(delay)
        return result


# ── Initialize local LLM client ──
llm_client = LocalLLMClient()

# ── Quick test ──
test_result = llm_client.call('Return JSON exactly: {"status": "ok", "mode": "local"}')
print(f"✅ Local LLM test response: {test_result}")

# %% [markdown]
# ## Cell 5: 📊 Step 1 — Load Data from Supabase

# %%
# ══════════════════════════════════════════════════════════════
# DATA LOADING from Supabase
# ══════════════════════════════════════════════════════════════

from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logger.info("Connected to Supabase.")

# ── Fetch Papers ──
logger.info("Fetching papers...")
papers_response = supabase.table("papers").select("*").execute()
df_papers = pd.DataFrame(papers_response.data)

# Rename columns to match pipeline expectations (Title Case)
col_rename = {
    "title": "Title", "abstract": "Abstract", "year": "Year",
    "journal": "Journal", "link": "Link", "doi": "DOI",
    "authors": "Authors", "author_ids": "Author IDs",
    "keywords": "Keywords", "tldr": "tldr",
}
df_papers.rename(columns={k: v for k, v in col_rename.items() if k in df_papers.columns}, inplace=True)

# Ensure required columns exist
for col in ["Title", "Abstract", "Year", "Journal", "Authors", "Author IDs", "Keywords", "Link", "DOI", "tldr"]:
    if col not in df_papers.columns:
        df_papers[col] = ""

logger.info(f"✅ Papers loaded: {len(df_papers)} rows")

# ── Fetch Lecturers (Dosen) ──
logger.info("Fetching lecturers...")
dosen_response = supabase.table("lecturers").select("*").execute()
df_dosen = pd.DataFrame(dosen_response.data)

# Ensure expected columns
dosen_col_rename = {
    "nama_dosen": "nama_dosen", "nama_norm": "nama_norm",
    "scholar_id": "scholar_id", "prodi": "prodi",
    "nip": "nip", "nidn": "nidn",
}
for col in ["nama_dosen", "nama_norm", "scholar_id", "prodi", "nip", "nidn"]:
    if col not in df_dosen.columns:
        df_dosen[col] = ""

logger.info(f"✅ Dosen loaded: {len(df_dosen)} rows")

# ── Preview ──
print("\n" + "="*60)
print(f"📄 Papers: {len(df_papers)} total")
print(f"   With abstract (>50 chars): {len(df_papers[df_papers['Abstract'].astype(str).str.len() > 50])}")
print(f"👨‍🏫 Dosen: {len(df_dosen)} total")
print("="*60)

display(df_papers[["Title", "Year", "Authors"]].head())
display(df_dosen[["nama_dosen", "prodi", "scholar_id"]].head())

# %% [markdown]
# ## Cell 6: 🏗️ Step 2-3 — Backbone + NER Extraction

# %%
# ══════════════════════════════════════════════════════════════
# STEP 2A — Load GLiNER & Constants
# ══════════════════════════════════════════════════════════════

from gliner import GLiNER

logger.info("=" * 60)
logger.info("STEP 2A: Loading GLiNER model...")
logger.info("=" * 60)
gliner_model = GLiNER.from_pretrained(
    GLINER_MODEL_NAME, load_tokenizer=True, resize_token_embeddings=True
)
logger.info(f"✅ GLiNER model loaded: {GLINER_MODEL_NAME}")

# Source priority constants
SRC_NER = 0
SRC_TITLE = 1
SRC_CSV = 2

GLINER_SET1 = ["method", "metric", "dataset", "task"]
GLINER_SET2 = ["problem", "model", "results", "innovation"]

print("✅ Step 2A ready")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 2B — EntityStore + NER Extraction Functions
# ══════════════════════════════════════════════════════════════

class EntityStore:
    def __init__(self):
        self.entities = OrderedDict()
        self._uid_counter = 0
        self._counts = {"ner": 0, "title": 0, "csv": 0}

    def register(self, text, label, source_priority):
        lemma_key = make_lemma_key(text)
        if not lemma_key or len(lemma_key) < 3:
            return None
        mapped_label = map_ner_label(label)
        if lemma_key not in self.entities:
            self.entities[lemma_key] = {
                "uid": self._uid_counter,
                "text": text.strip(),
                "label": mapped_label,
                "count": 1,
                "source": source_priority,
                "description": "",
            }
            self._uid_counter += 1
            src_name = ["ner", "title", "csv"][min(source_priority, 2)]
            self._counts[src_name] += 1
        elif source_priority < self.entities[lemma_key]["source"]:
            self.entities[lemma_key]["text"] = text.strip()
            self.entities[lemma_key]["label"] = mapped_label
            self.entities[lemma_key]["source"] = source_priority
            self.entities[lemma_key]["count"] += 1
        else:
            self.entities[lemma_key]["count"] += 1
        return lemma_key

    def get(self, lemma_key):
        return self.entities.get(lemma_key)

    def get_all_texts(self):
        return [e["text"] for e in self.entities.values()]

    @property
    def stats(self):
        return {
            "unique_entities": len(self.entities),
            "from_ner": self._counts["ner"],
            "from_title_regex": self._counts["title"],
            "from_csv_keywords": self._counts["csv"],
        }

    def __len__(self):
        return len(self.entities)

    def __contains__(self, lemma_key):
        return lemma_key in self.entities


def extract_entities_from_paper(title, text, csv_keywords="", entity_store=None, threshold=GLINER_THRESHOLD):
    if entity_store is None:
        entity_store = EntityStore()

    paper_lemma_keys = []
    full_text = f"{title}. {text}"
    input_text = truncate(full_text, 2000)

    # Pass 1: GLiNER NER
    for label_set in [GLINER_SET1, GLINER_SET2]:
        try:
            ents = gliner_model.predict_entities(input_text, label_set, threshold=threshold)
            for e in ents:
                lk = entity_store.register(e["text"], e["label"], SRC_NER)
                if lk:
                    paper_lemma_keys.append(lk)
        except Exception as ex:
            logger.debug(f"GLiNER error: {type(ex).__name__}: {ex}")

    # Pass 2: Title regex (acronyms + CamelCase)
    for term in re.findall(r"[A-Z]{2,}[0-9]*", title):
        lk = entity_store.register(term, "method", SRC_TITLE)
        if lk:
            paper_lemma_keys.append(lk)

    for term in re.findall(r"[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)+", title):
        lk = entity_store.register(term, "method", SRC_TITLE)
        if lk:
            paper_lemma_keys.append(lk)

    # Pass 3: CSV Keywords
    if csv_keywords and csv_keywords.lower() != "nan":
        for kw in re.split(r"[;,]", csv_keywords):
            kw = kw.strip()
            if kw and len(kw) > 2:
                lk = entity_store.register(kw, "field", SRC_CSV)
                if lk:
                    paper_lemma_keys.append(lk)

    return entity_store, list(set(paper_lemma_keys))

print("✅ Step 2B ready")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 2C — Backbone Builder
# ══════════════════════════════════════════════════════════════

def _dosen_id(sid, name):
    return f"dosen_{sid}" if sid else f"dosen_{md5(name)}"

def _prodi_id(prodi):
    return f'prodi_{normalize_text(prodi).replace(" ", "_")}'

def _paper_id(title):
    return f"paper_{md5(title)}"

def _year_id(year):
    return f"year_{year}"

def _journal_id(journal_name):
    return f"journal_{md5(journal_name)}"

def _keyword_id(keyword):
    return f"keyword_{md5(keyword)}"

def build_backbone(df_papers, df_dosen):
    nodes = {}
    edges = []
    paper_abstracts = {}
    paper_titles = {}
    text_chunks_db = {}

    dosen_lookup = {}
    dosen_name_lookup = {}
    for _, r in df_dosen.iterrows():
        sid = safe_str(r.get("scholar_id"))
        name = safe_str(r.get("nama_norm")) or safe_str(r.get("nama_dosen"))
        if sid:
            dosen_lookup[sid.strip()] = r.to_dict()
        if name and sid:
            dosen_name_lookup[name.lower().strip()] = sid

    dosen_count = 0
    for _, row in df_dosen.iterrows():
        name = safe_str(row.get("nama_norm")) or safe_str(row.get("nama_dosen"))
        if not name:
            continue
        sid = safe_str(row.get("scholar_id"))
        d_id = _dosen_id(sid, name)
        prodi = safe_str(row.get("prodi"), "Unknown")
        nodes[d_id] = {
            "_label": "Dosen", "name": name, "prodi": prodi,
            "scholar_id": sid, "nip": safe_str(row.get("nip")),
            "nidn": safe_str(row.get("nidn")),
        }
        p_id = _prodi_id(prodi)
        if p_id not in nodes:
            nodes[p_id] = {"_label": "ProgramStudi", "name": prodi}
        edges.append((d_id, p_id, "MEMBER_OF", {}))
        dosen_count += 1

    logger.info(f"Dosen backbone: {dosen_count} dosen registered")

    df_with_abstract = df_papers[df_papers["Abstract"].astype(str).str.len() > 50]
    logger.info(f"Papers with abstracts (>50 chars): {len(df_with_abstract)}")

    paper_count, keyword_count, skipped_external = 0, 0, 0

    for _, row in df_with_abstract.iterrows():
        t = safe_str(row.get("Title"))
        if not t:
            continue
        a = safe_str(row.get("Abstract"))
        y = safe_str(row.get("Year"))[:4] if safe_str(row.get("Year")) else ""
        journal = safe_str(row.get("Journal"))
        link = safe_str(row.get("Link"))
        doi = safe_str(row.get("DOI"))
        if ("scholar" in link.lower() or not link) and doi:
            link = f"https://doi.org/{doi}"
        tldr = safe_str(row.get("tldr"))
        text_for_analysis = tldr if len(tldr) > 20 else a

        pid = _paper_id(t)
        chunk_id = f"chunk_{md5(t)}"
        nodes[pid] = {
            "_label": "Paper", "title": t, "year": y,
            "url": link, "journal": journal, "source_id": chunk_id,
        }
        paper_abstracts[pid] = text_for_analysis
        paper_titles[pid] = t
        paper_count += 1

        text_chunks_db[chunk_id] = {
            "content": text_for_analysis, "paper_id": pid,
            "title": t, "full_content": f"{t}. {text_for_analysis}",
        }

        if y:
            yid = _year_id(y)
            if yid not in nodes:
                nodes[yid] = {"_label": "Year", "value": y}
            edges.append((pid, yid, "PUBLISHED_YEAR", {}))

        j_clean = journal.split(",")[0].strip() if journal else ""
        if j_clean:
            jid = _journal_id(j_clean)
            if jid not in nodes:
                nodes[jid] = {"_label": "Journal", "name": j_clean}
            edges.append((pid, jid, "PUBLISHED_IN", {}))

        authors = [x.strip() for x in str(row.get("Authors", "")).split(",") if x.strip()]
        aids = [x.strip() for x in str(row.get("Author IDs", "")).split(";") if x.strip()]
        for i, aname in enumerate(authors):
            if not aname or aname.lower() == "nan":
                continue
            asid = aids[i] if i < len(aids) else ""
            is_internal = asid and asid in dosen_lookup
            if not is_internal:
                matched_sid = dosen_name_lookup.get(aname.lower().strip())
                if matched_sid:
                    asid = matched_sid
                    is_internal = True
            if is_internal:
                did = f"dosen_{asid}"
                edges.append((did, pid, "WRITES", {"position": "first" if i == 0 else "co"}))
            else:
                skipped_external += 1

        kw_raw = safe_str(row.get("Keywords"))
        if kw_raw:
            for kw in re.split(r"[;,]", kw_raw):
                kw = kw.strip()
                if kw and len(kw) > 2:
                    kwid = _keyword_id(kw)
                    if kwid not in nodes:
                        nodes[kwid] = {"_label": "Keyword", "name": kw}
                        keyword_count += 1
                    edges.append((pid, kwid, "HAS_KEYWORD", {}))

    logger.info(
        f"Backbone: {paper_count} papers, {dosen_count} dosen, "
        f"{skipped_external} external skipped, {keyword_count} keywords | "
        f"Nodes: {len(nodes)}, Edges: {len(edges)}"
    )
    return nodes, edges, paper_abstracts, paper_titles, text_chunks_db

print("✅ Step 2C ready")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 2D — Run Backbone
# ══════════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("STEP 2D: Building backbone graph...")
logger.info("=" * 60)

nodes, edges, paper_abstracts, paper_titles, text_chunks_db = build_backbone(df_papers, df_dosen)

print("✅ Backbone complete")
print(f"   Nodes: {len(nodes)}")
print(f"   Edges: {len(edges)}")
print(f"   Papers with abstracts: {len(paper_abstracts)}")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 3 — Run NER Extraction
# ══════════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("STEP 3: Running NER extraction...")
logger.info("=" * 60)

entity_store = EntityStore()
extracted_entities = {}  # {paper_id: [lemma_keys]}

total_papers = len(paper_abstracts)
for i, (pid, abstract) in enumerate(paper_abstracts.items(), start=1):
    title = paper_titles.get(pid, "")
    csv_kw = ""
    match = df_papers[df_papers["Title"] == title]
    if not match.empty:
        csv_kw = safe_str(match.iloc[0].get("Keywords", ""))

    entity_store, lemma_keys = extract_entities_from_paper(
        title, abstract, csv_kw, entity_store, GLINER_THRESHOLD
    )
    extracted_entities[pid] = lemma_keys

    if i % 10 == 0 or i == total_papers:
        logger.info(
            f"  NER Progress: {i}/{total_papers} papers | "
            f"{len(entity_store)} unique entities"
        )

print("✅ NER extraction complete")
print(f"   {entity_store.stats}")

# %% [markdown]
# ## Cell 7: 🔗 Step 4-5 — Entity Resolution + LLM Curation

# %%
# ══════════════════════════════════════════════════════════════
# STEP 4A — Entity Resolution Rules + Prompts
# ══════════════════════════════════════════════════════════════

# ── Abbreviation regex patterns ──
_ABBR_PAT1 = re.compile(r"([A-Za-z][\w\s\-]+?)\s*\(([A-Z][A-Za-z0-9\s\-\.]*?)\)")
_ABBR_PAT2 = re.compile(r"([A-Z][A-Z0-9]{1,10})\s*\(([A-Za-z][\w\s\-]+?)\)")

# ── LLM Prompts ──
_CLUSTER_PROMPT = (
    "Kamu ahli Entity Resolution untuk KG akademik.\n"
    "Kelompokkan entitas yang BERMAKNA SAMA (sinonim, singkatan, terjemahan).\n\n"
    'Contoh: "QoS" = "Quality of Service" | "CNN" = "Convolutional Neural Network" | "akurasi" = "accuracy"\n\n'
    "Daftar entitas:\n{ents}\n\n"
    'Output JSON: {{"groups": [{{"canonical": "English standard name", "members": ["var1", "var2"]}}]}}\n'
    "Hanya kelompokkan yang BENAR-BENAR sinonim. Entitas unik tidak perlu dimasukkan."
)

_CURATION_PROMPT = (
    "Kamu ahli NLP. Validasi dan perkaya entitas dari paper akademik ini.\n\n"
    "## Judul: {title}\n"
    "## Abstrak: {abstract}\n"
    "## Entitas terdeteksi NER (mungkin noisy): {entities}\n\n"
    "## Tugas:\n"
    "1. VALIDASI: hapus yang bukan entitas ilmiah (kata umum).\n"
    "2. PERBAIKI label jika salah. Label valid: Method, Model, Metric, Dataset, Problem, Task, Field, Tool, Innovation\n"
    "3. TAMBAHKAN entitas penting yang terlewat oleh NER.\n"
    "4. Berikan DESCRIPTION 1 kalimat per entitas (untuk vector search).\n"
    "5. Ekstrak RELASI antar entitas: USES (source uses target), ADDRESSES, PROPOSES\n\n"
    "## Output JSON:\n"
    '{{ "entities": [{{"text": "exact text", "label": "Method", "description": "1 sentence"}}],\n'
    '  "relations": [{{"source": "entity1", "target": "entity2", "relation": "USES", "description": "1 sentence"}}] }}\n\n'
    "PENTING: Entitas harus text spans yang ADA di abstrak/judul. Minimal 3 entitas per abstrak."
)

def extract_abbreviations(paper_abstracts, paper_titles):
    alias_map = {}
    for pid, abstract in paper_abstracts.items():
        title = paper_titles.get(pid, "")
        full = f"{title}. {abstract}"
        for pat in [_ABBR_PAT1, _ABBR_PAT2]:
            for m in pat.finditer(full):
                a, b = m.group(1).strip(), m.group(2).strip()
                short, long_ = (a, b) if len(a) < len(b) else (b, a)
                if len(short) >= 2:
                    lk_short = make_lemma_key(short)
                    lk_long = make_lemma_key(long_)
                    if lk_short and lk_long and lk_short != lk_long:
                        alias_map[lk_short] = lk_long
    logger.info(f"Layer 2 (Regex): {len(alias_map)} abbreviation aliases")
    return alias_map

def cluster_synonyms_llm(entity_texts, llm_client, batch_size=LLM_BATCH_SIZE):
    alias_map = {}
    cluster_count, batch_count = 0, 0
    for start in range(0, len(entity_texts), batch_size):
        batch = entity_texts[start:start + batch_size]
        if len(batch) < 2:
            continue
        batch_count += 1
        ents_str = "\n".join([f"- {e}" for e in batch])
        result = llm_client.call_with_delay(_CLUSTER_PROMPT.format(ents=ents_str), delay=0.4)
        for grp in result.get("groups", []):
            if not isinstance(grp, dict):
                continue
            canonical = grp.get("canonical", "")
            members = grp.get("members", [])
            if canonical and len(members) > 1:
                lk_canon = make_lemma_key(canonical)
                for member in members:
                    lk_mem = make_lemma_key(member)
                    if lk_mem and lk_mem != lk_canon:
                        alias_map[lk_mem] = lk_canon
                cluster_count += 1
        if batch_count % 5 == 0:
            logger.info(f"  LLM clustering batch {batch_count}...")
    logger.info(f"Layer 3 (LLM): {cluster_count} synonym clusters from {batch_count} batches")
    return alias_map

def resolve(lemma_key, alias_map):
    visited = set()
    while lemma_key in alias_map and lemma_key not in visited:
        visited.add(lemma_key)
        lemma_key = alias_map[lemma_key]
    return lemma_key

def apply_resolution(extracted_entities, alias_map):
    merged_count = 0
    for pid in extracted_entities:
        resolved = []
        for lk in extracted_entities[pid]:
            canon = resolve(lk, alias_map)
            if canon != lk:
                merged_count += 1
            resolved.append(canon)
        extracted_entities[pid] = list(set(resolved))
    return merged_count

print("✅ Step 4A ready")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 4B — Run Entity Resolution
# ══════════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("STEP 4B: Entity Resolution...")
logger.info("=" * 60)

alias_map = extract_abbreviations(paper_abstracts, paper_titles)
llm_aliases = cluster_synonyms_llm(entity_store.get_all_texts(), llm_client, LLM_BATCH_SIZE)
alias_map.update(llm_aliases)

merged_count = apply_resolution(extracted_entities, alias_map)

print("✅ Entity resolution complete")
print(f"   Alias mappings: {len(alias_map)}")
print(f"   Merged references: {merged_count}")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 5A — LLM Curation Helper Functions
# ══════════════════════════════════════════════════════════════

def _parse_curated_entity(ent, alias_map, valid_labels):
    if not isinstance(ent, dict):
        return None, None, None, None, None

    txt = str(ent.get("text", "")).strip()
    lbl = str(ent.get("label", "Field")).strip()
    desc = str(ent.get("description", "")).strip()
    lbl_cap = lbl.capitalize()

    if lbl_cap not in valid_labels:
        lbl_cap = map_ner_label(lbl)

    if not txt or len(txt) < 2:
        return None, None, None, None, None

    lk = resolve(make_lemma_key(txt), alias_map)
    nid = f"{lbl_cap.lower()}_{md5(lk)}"
    return lk, nid, txt, lbl_cap, desc

def _parse_curated_relation(rel, entity_node_map, alias_map):
    if not isinstance(rel, dict):
        return None, None, None, None

    slk = resolve(make_lemma_key(str(rel.get("source", ""))), alias_map)
    tlk = resolve(make_lemma_key(str(rel.get("target", ""))), alias_map)

    if slk in entity_node_map and tlk in entity_node_map:
        rtype = str(rel.get("relation", "USES")).upper().replace(" ", "_")
        rdesc = str(rel.get("description", ""))
        return entity_node_map[slk], entity_node_map[tlk], rtype, rdesc

    return None, None, None, None

def curate_entities_llm(
    extracted_entities, entity_store, paper_abstracts, paper_titles,
    alias_map, nodes, edges, llm_client, text_chunks_db=None,
):
    entity_vdb, relationship_vdb, keywords_vdb = [], [], []
    entity_node_map = {}
    valid_labels = get_valid_semantic_labels()
    curated_ent_count, curated_rel_count, llm_errors, skipped = 0, 0, 0, 0

    for i, (pid, lemma_keys) in enumerate(extracted_entities.items(), start=1):
        abstract = paper_abstracts.get(pid, "")
        title = paper_titles.get(pid, "")
        if len(abstract) < 50:
            skipped += 1
            continue

        ent_hints = [
            {"text": entity_store.get(lk)["text"], "label": entity_store.get(lk)["label"]}
            for lk in lemma_keys if lk in entity_store
        ]

        enriched = llm_client.call_with_delay(
            _CURATION_PROMPT.format(
                title=title,
                abstract=truncate(abstract, 2000),
                entities=json.dumps(ent_hints, ensure_ascii=False),
            )
        )

        if not enriched or not isinstance(enriched, dict):
            llm_errors += 1
            continue

        for ent in enriched.get("entities", []):
            lk, nid, txt, lbl_cap, desc = _parse_curated_entity(ent, alias_map, valid_labels)
            if not lk:
                continue

            paper_source_id = nodes.get(pid, {}).get("source_id", "")
            if lk not in entity_node_map:
                entity_node_map[lk] = nid
                nodes[nid] = {
                    "_label": lbl_cap,
                    "name": txt,
                    "description": desc,
                    "source_id": paper_source_id,
                }
                entity_vdb.append({
                    "nodeId": nid,
                    "entityName": txt,
                    "entityType": lbl_cap,
                    "description": desc,
                    "sourceId": paper_source_id,
                })
                curated_ent_count += 1

                if lk in entity_store:
                    entity_store.entities[lk]["description"] = desc

            edges.append((pid, entity_node_map[lk], f"HAS_{lbl_cap.upper()}", {}))

        for rel in enriched.get("relations", []):
            src_nid, tgt_nid, rtype, rdesc = _parse_curated_relation(rel, entity_node_map, alias_map)
            if not src_nid:
                continue

            paper_source_id = nodes.get(pid, {}).get("source_id", "")
            edges.append((src_nid, tgt_nid, rtype, {"description": rdesc}))
            relationship_vdb.append({
                "srcId": src_nid,
                "tgtId": tgt_nid,
                "relType": rtype,
                "description": rdesc,
                "sourceId": paper_source_id,
            })
            curated_rel_count += 1

        kws = [entity_store.get(lk)["text"] for lk in lemma_keys if lk in entity_store]
        if kws:
            keywords_vdb.append({"keywords": "; ".join(kws), "sourcePaper": pid})

        if i % 5 == 0 or i == len(extracted_entities):
            logger.info(
                f"  Curated {i}/{len(extracted_entities)} | "
                f"ent: {curated_ent_count} | rel: {curated_rel_count} | err: {llm_errors}"
            )

    logger.info(
        f"LLM Curation complete: {curated_ent_count} entities, "
        f"{curated_rel_count} relations, {llm_errors} errors"
    )

    return nodes, edges, entity_vdb, relationship_vdb, keywords_vdb, entity_node_map

print("✅ Step 5A ready")

# %%
# ══════════════════════════════════════════════════════════════
# STEP 5B — Run LLM Curation
# ══════════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("STEP 5B: LLM Curation...")
logger.info("=" * 60)

nodes, edges, entity_vdb, relationship_vdb, keywords_vdb, entity_node_map = curate_entities_llm(
    extracted_entities,
    entity_store,
    paper_abstracts,
    paper_titles,
    alias_map,
    nodes,
    edges,
    llm_client,
    text_chunks_db,
 )

print("✅ LLM curation complete")
print(f"   Total nodes: {len(nodes)}")
print(f"   Total edges: {len(edges)}")
print(f"   Entity VDB records: {len(entity_vdb)}")
print(f"   Relationship VDB records: {len(relationship_vdb)}")
print(f"   LLM stats: {llm_client.stats}")

# %% [markdown]
# ## Cell 8: 💾 Step 6 — Write to Neo4j AuraDB

# %%
# ══════════════════════════════════════════════════════════════
# NEO4J AURADB WRITER
# Ported from: neo4j_writer.py
# Connection: neo4j+s:// (AuraDB encrypted)
# ══════════════════════════════════════════════════════════════

from neo4j import GraphDatabase


class Neo4jKGWriter:
    def __init__(self, uri=None, user=None, password=None, database=None):
        self.uri = uri or NEO4J_URI
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self.database = database or NEO4J_DATABASE

        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            logger.info(f"✅ Neo4j connected to {self.uri} (db={self.database})")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neo4j: {e}")
            raise

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j driver closed.")

    def _session(self):
        return self.driver.session(database=self.database)

    def clear_database(self):
        with self._session() as s:
            s.run("MATCH (n) DETACH DELETE n")
            logger.info("⚠️ Neo4j: all existing data DELETED")

    def ensure_constraints(self):
        labels = get_all_labels()
        with self._session() as s:
            for lbl in labels:
                s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.node_id IS UNIQUE")
        logger.info(f"  Neo4j: {len(labels)} uniqueness constraints ensured")

    def ingest_nodes(self, nodes):
        logger.info(f"Ingesting {len(nodes)} nodes to Neo4j...")
        errors = 0
        label_counts = {}
        t0 = time.time()
        with self._session() as s:
            for nid, d in nodes.items():
                try:
                    lbl = d["_label"]
                    props = {
                        k: str(v) for k, v in d.items()
                        if k != "_label" and v and str(v) != "nan"
                    }
                    props["node_id"] = nid
                    set_clause = ", ".join([f"n.`{k}` = ${k}" for k in props])
                    s.run(f"MERGE (n:{lbl} {{node_id: $node_id}}) SET {set_clause}", **props)
                    label_counts[lbl] = label_counts.get(lbl, 0) + 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Node error [{nid}]: {e}")
        elapsed = time.time() - t0
        logger.info(f"  Neo4j nodes done in {elapsed:.1f}s (errors: {errors})")
        return {"label_counts": label_counts, "errors": errors}

    def ingest_edges(self, edges, nodes):
        logger.info(f"Ingesting {len(edges)} edges to Neo4j...")
        errors, skipped = 0, 0
        rel_counts = {}
        t0 = time.time()
        with self._session() as s:
            for src, tgt, rel, props in edges:
                if src not in nodes or tgt not in nodes:
                    skipped += 1
                    continue
                try:
                    prop_clause = ""
                    if props:
                        sp = [f'r.`{k}` = "{v}"' for k, v in props.items() if v]
                        if sp:
                            prop_clause = " SET " + ", ".join(sp)
                    s.run(
                        f"MATCH (a {{node_id: $s}}) MATCH (b {{node_id: $t}}) "
                        f"MERGE (a)-[r:{rel}]->(b){prop_clause}",
                        s=src, t=tgt,
                    )
                    rel_counts[rel] = rel_counts.get(rel, 0) + 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Edge error [{src}]-[{rel}]→[{tgt}]: {e}")
        elapsed = time.time() - t0
        logger.info(f"  Neo4j edges done in {elapsed:.1f}s (errors: {errors}, skipped: {skipped})")
        return {"rel_counts": rel_counts, "errors": errors, "skipped": skipped}

    def derive_collaborations(self):
        cypher = """
        MATCH (a:Dosen)-[:WRITES]->(p:Paper)<-[:WRITES]-(b:Dosen)
        WHERE elementId(a) < elementId(b)
        WITH a, b, COLLECT(DISTINCT p.node_id) AS paper_ids
        MERGE (a)-[r:COLLABORATES_WITH]->(b)
        SET r.papers = paper_ids,
            r.count = SIZE(paper_ids),
            r.updated_at = toString(datetime())
        RETURN COUNT(r) AS total
        """
        with self._session() as s:
            result = s.run(cypher).single()
            total = result["total"] if result else 0
            logger.info(f"  COLLABORATES_WITH edges derived: {total}")
            return total

    def get_stats(self):
        with self._session() as s:
            nc = s.run("MATCH (n) RETURN count(n) as c").single()["c"]
            ec = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
            lc = s.run("MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt ORDER BY cnt DESC").data()
            rc = s.run("MATCH ()-[r]->() RETURN type(r) as relType, count(r) as cnt ORDER BY cnt DESC").data()
        return {
            "node_count": nc, "edge_count": ec,
            "label_distribution": {r["label"]: r["cnt"] for r in lc},
            "rel_distribution": {r["relType"]: r["cnt"] for r in rc},
        }

    def print_summary(self):
        stats = self.get_stats()
        sep = "=" * 60
        print(f"\n{sep}")
        print("🎉 KG CONSTRUCTION PIPELINE COMPLETE!")
        print(sep)
        print(f"Neo4j: {stats['node_count']} nodes, {stats['edge_count']} edges")
        print("\n--- Node Distribution ---")
        for label, cnt in stats["label_distribution"].items():
            print(f"  {label:20s}: {cnt}")
        print("\n--- Edge Distribution ---")
        for rel, cnt in stats["rel_distribution"].items():
            print(f"  {rel:20s}: {cnt}")
        print(sep)


# ══════════════════════════════════════════════════════════════
# RUN NEO4J INGESTION
# ══════════════════════════════════════════════════════════════

logger.info("="*60)
logger.info("STEP 6: Writing to Neo4j AuraDB...")
logger.info("="*60)

neo4j_writer = Neo4jKGWriter()

if CLEAR_NEO4J_BEFORE_INGEST:
    neo4j_writer.clear_database()

neo4j_writer.ensure_constraints()
node_stats = neo4j_writer.ingest_nodes(nodes)
edge_stats = neo4j_writer.ingest_edges(edges, nodes)
collab_count = neo4j_writer.derive_collaborations()

neo4j_writer.print_summary()
neo4j_writer.close()

# %% [markdown]
# ## Cell 9: 🔮 Step 7 — Write to Zilliz Cloud (Vector DB)

# %%
# ══════════════════════════════════════════════════════════════
# ZILLIZ CLOUD WRITER (Managed Milvus)
# Ported from: milvus_writer.py
# Uses MilvusClient API for Zilliz Cloud connection
# ══════════════════════════════════════════════════════════════

if not ENABLE_ZILLIZ:
    print("⏭️ Zilliz Cloud ingestion SKIPPED (ENABLE_ZILLIZ = False)")
else:
    from pymilvus import MilvusClient, DataType
    from sentence_transformers import SentenceTransformer

    # ── Load Embedding Model ──
    EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
    logger.info(f"Loading embedding model: {EMBED_MODEL_NAME}...")
    embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    logger.info(f"✅ Embedding model loaded")

    # ── Connect to Zilliz Cloud ──
    logger.info(f"Connecting to Zilliz Cloud: {ZILLIZ_URI}")
    milvus_client = MilvusClient(uri=ZILLIZ_URI, token=ZILLIZ_TOKEN)
    logger.info(f"✅ Connected to Zilliz Cloud")

    # ── Collection Definitions ──
    COLLECTIONS = {
        "EntityEmbedding": {
            "embed_field": "description",
            "fields": [
                {"name": "id", "dtype": DataType.INT64, "is_primary": True, "auto_id": True},
                {"name": "entityName", "dtype": DataType.VARCHAR, "max_length": 512},
                {"name": "entityType", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "description", "dtype": DataType.VARCHAR, "max_length": 4096},
                {"name": "nodeId", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "sourceId", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": EMBEDDING_DIM},
            ],
        },
        "RelationshipEmbedding": {
            "embed_field": "description",
            "fields": [
                {"name": "id", "dtype": DataType.INT64, "is_primary": True, "auto_id": True},
                {"name": "srcId", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "tgtId", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "relType", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "description", "dtype": DataType.VARCHAR, "max_length": 4096},
                {"name": "sourceId", "dtype": DataType.VARCHAR, "max_length": 256},
                {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": EMBEDDING_DIM},
            ],
        },
        "ContentKeyword": {
            "embed_field": "keywords",
            "fields": [
                {"name": "id", "dtype": DataType.INT64, "is_primary": True, "auto_id": True},
                {"name": "keywords", "dtype": DataType.VARCHAR, "max_length": 2048},
                {"name": "sourcePaper", "dtype": DataType.VARCHAR, "max_length": 512},
                {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": EMBEDDING_DIM},
            ],
        },
        "PaperChunk": {
            "embed_field": "content",
            "fields": [
                {"name": "id", "dtype": DataType.INT64, "is_primary": True, "auto_id": True},
                {"name": "title", "dtype": DataType.VARCHAR, "max_length": 1024},
                {"name": "content", "dtype": DataType.VARCHAR, "max_length": 8192},
                {"name": "year", "dtype": DataType.VARCHAR, "max_length": 16},
                {"name": "paperUrl", "dtype": DataType.VARCHAR, "max_length": 1024},
                {"name": "authors", "dtype": DataType.VARCHAR, "max_length": 2048},
                {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": EMBEDDING_DIM},
            ],
        },
    }


    def _get_max_len(fields, field_name):
        for f in fields:
            if f["name"] == field_name and "max_length" in f:
                return f["max_length"]
        return 4096


    def ensure_collections(client, recreate=True):
        """Create all 4 Zilliz Cloud collections."""
        from pymilvus import CollectionSchema, FieldSchema

        for name, spec in COLLECTIONS.items():
            existing = client.list_collections()
            if name in existing:
                if recreate:
                    client.drop_collection(name)
                    logger.info(f"  Dropped existing collection: {name}")
                else:
                    logger.info(f"  Collection exists (kept): {name}")
                    continue

            # Build schema
            field_schemas = []
            for f_def in spec["fields"]:
                kwargs = {k: v for k, v in f_def.items() if k != "dtype"}
                kwargs["dtype"] = f_def["dtype"]
                field_schemas.append(FieldSchema(**kwargs))

            schema = CollectionSchema(fields=field_schemas, description=f"KG {name}")
            client.create_collection(collection_name=name, schema=schema)

            # Create index on embedding field
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="AUTOINDEX",
                metric_type="L2",
            )
            client.create_index(collection_name=name, index_params=index_params)
            client.load_collection(name)

            logger.info(f"  Created collection: {name} (AUTOINDEX, dim={EMBEDDING_DIM})")


    def ingest_to_zilliz(client, collection_name, data, batch_size=50):
        """Batch-insert data into a Zilliz Cloud collection."""
        if not data:
            logger.info(f"  {collection_name}: no data to ingest")
            return 0

        spec = COLLECTIONS[collection_name]
        embed_field = spec["embed_field"]
        data_field_names = [f["name"] for f in spec["fields"] if f["name"] not in ("id", "embedding")]
        batch_errors = 0

        for start in range(0, len(data), batch_size):
            try:
                batch = data[start:start + batch_size]
                texts_to_embed = [str(item.get(embed_field, "")) for item in batch]
                embeddings = embed_model.encode(texts_to_embed).tolist()

                insert_rows = []
                for i, item in enumerate(batch):
                    row = {}
                    for fname in data_field_names:
                        max_len = _get_max_len(spec["fields"], fname)
                        row[fname] = str(item.get(fname, ""))[:max_len]
                    row["embedding"] = embeddings[i]
                    insert_rows.append(row)

                client.insert(collection_name=collection_name, data=insert_rows)

            except Exception as e:
                batch_errors += 1
                logger.error(f"Zilliz batch error [{collection_name}] at {start}: {type(e).__name__}: {e}")

        logger.info(f"  {collection_name}: {len(data)} objects (batch errors: {batch_errors})")
        return batch_errors


    # ── Build PaperChunk data ──
    chunk_vdb = []
    for chunk_id, chunk_data in text_chunks_db.items():
        pid = chunk_data["paper_id"]
        paper_node = nodes.get(pid, {})
        chunk_vdb.append({
            "title": chunk_data["title"],
            "content": chunk_data.get("full_content", chunk_data["content"]),
            "year": paper_node.get("year", ""),
            "paperUrl": paper_node.get("url", ""),
            "authors": "",  # Can be enriched if needed
        })

    # ── RUN ZILLIZ INGESTION ──
    logger.info("="*60)
    logger.info("STEP 7: Writing to Zilliz Cloud...")
    logger.info("="*60)

    ensure_collections(milvus_client, recreate=True)

    ingest_to_zilliz(milvus_client, "EntityEmbedding", entity_vdb)
    ingest_to_zilliz(milvus_client, "RelationshipEmbedding", relationship_vdb)
    ingest_to_zilliz(milvus_client, "ContentKeyword", keywords_vdb)
    ingest_to_zilliz(milvus_client, "PaperChunk", chunk_vdb)

    # Verify
    print("\n" + "="*60)
    print("🔮 Zilliz Cloud Ingestion Summary")
    print("="*60)
    for coll_name in COLLECTIONS:
        try:
            milvus_client.flush(coll_name)
        except Exception:
            pass
        stats = milvus_client.get_collection_stats(coll_name)
        print(f"  {coll_name}: {stats.get('row_count', 'N/A')} rows")
    print("="*60)
    print("\n🎉 FULL PIPELINE COMPLETE!")


# %%



