# ══════════════════════════════════════════════════════════════════════
# CELL 1: Setup & Academic Ontology
# ══════════════════════════════════════════════════════════════════════
import pandas as pd
import json, os, requests, time, warnings, hashlib, re, logging, sys
from collections import defaultdict, OrderedDict
from datetime import datetime
warnings.filterwarnings('ignore')

from neo4j import GraphDatabase
import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.data import DataObject
from dotenv import load_dotenv
from gliner import GLiNER
import spacy

# ── Production Logging Setup ──
LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f'kg_pipeline_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

logger = logging.getLogger('kg_pipeline')
logger.setLevel(logging.DEBUG)
logger.handlers.clear()

# File handler: DEBUG (captures everything for post-mortem debugging)
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# Console handler: DEBUG (shows all progress directly in notebook output)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter('%(levelname)-8s | %(message)s'))
logger.addHandler(ch)

# Suppress verbose HTTP connection logs from requests library
logging.getLogger('urllib3').setLevel(logging.WARNING)

# Pipeline timer utility
_cell_timers = {}
def start_cell(cell_name):
    _cell_timers[cell_name] = time.time()
    logger.info(f'{"="*60}')
    logger.info(f'START: {cell_name}')
    logger.info(f'{"="*60}')

def end_cell(cell_name, stats=None):
    elapsed = time.time() - _cell_timers.get(cell_name, time.time())
    logger.info(f'{"─"*60}')
    if stats:
        for k, v in stats.items():
            logger.info(f'  {k}: {v}')
    logger.info(f'✅ {cell_name} completed in {elapsed:.1f}s')
    logger.info(f'{"="*60}\n')

start_cell('Cell 1: Setup & Ontology')

load_dotenv('../../.env')
NEO4J_URI   = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER  = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASS  = os.getenv('NEO4J_PASS', 'rizkyyk123')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
WEAVIATE_HOST = os.getenv('WEAVIATE_HOST', 'localhost')
WEAVIATE_PORT = int(os.getenv('WEAVIATE_PORT', '8081'))
LLM_MODEL = 'nvidia/nemotron-3-super-120b-a12b:free'

logger.info(f'Config: NEO4J={NEO4J_URI}, WEAVIATE={WEAVIATE_HOST}:{WEAVIATE_PORT}')
logger.info(f'LLM Model: {LLM_MODEL}')
logger.debug(f'OpenRouter API key loaded: {"YES" if OPENROUTER_API_KEY else "MISSING!"}')

# ── Academic Ontology (equivalent to Strwythura's domain.ttl) ──
ONTOLOGY = {
    'node_types': {
        'Dosen': {'description': 'Internal faculty member'},
        'ExternalAuthor': {'description': 'Non-faculty co-author'},
        'Paper': {'description': 'Research publication'},
        'ProgramStudi': {'description': 'Study program / department'},
        'Fakultas': {'description': 'Faculty / college'},
        'Journal': {'description': 'Publication venue'},
        'Year': {'description': 'Publication year'},
        'Keyword': {'description': 'Author-assigned keyword'},
        'Method': {'description': 'Research method or algorithm'},
        'Model': {'description': 'ML/AI model architecture'},
        'Metric': {'description': 'Evaluation metric'},
        'Dataset': {'description': 'Dataset used in study'},
        'Problem': {'description': 'Research problem addressed'},
        'Task': {'description': 'Computational/research task'},
        'Field': {'description': 'Research domain/field'},
        'Tool': {'description': 'Software tool or framework'},
        'Innovation': {'description': 'Novel contribution'},
    },
    'edge_types': {
        'WRITES': ('Dosen/ExternalAuthor', 'Paper'),
        'MEMBER_OF': ('Dosen', 'ProgramStudi'),
        'PART_OF': ('ProgramStudi', 'Fakultas'),
        'PUBLISHED_YEAR': ('Paper', 'Year'),
        'PUBLISHED_IN': ('Paper', 'Journal'),
        'HAS_KEYWORD': ('Paper', 'Keyword'),
        'HAS_METHOD': ('Paper', 'Method'),
        'HAS_MODEL': ('Paper', 'Model'),
        'HAS_METRIC': ('Paper', 'Metric'),
        'HAS_DATASET': ('Paper', 'Dataset'),
        'ADDRESSES': ('Paper', 'Problem'),
        'HAS_TASK': ('Paper', 'Task'),
        'IN_FIELD': ('Paper', 'Field'),
        'HAS_TOOL': ('Paper', 'Tool'),
        'PROPOSES': ('Paper', 'Innovation'),
        'USES': ('Entity', 'Entity'),
    },
    'ner_labels': ['method', 'model', 'metric', 'dataset', 'problem', 'task', 'field', 'tool', 'innovation'],
    'ner_label_map': {
        'method': 'Method', 'model': 'Model', 'metric': 'Metric',
        'dataset': 'Dataset', 'problem': 'Problem', 'task': 'Task',
        'field': 'Field', 'tool': 'Tool', 'innovation': 'Innovation',
        'algorithm': 'Method', 'technique': 'Method', 'framework': 'Tool',
        'software': 'Tool', 'platform': 'Tool', 'evaluation metric': 'Metric',
        'research method': 'Method', 'scientific concept': 'Field',
        'technology': 'Tool', 'programming language': 'Tool',
    },
}

PRODI_FAKULTAS = {
    'S1 Teknik Informatika': 'Fakultas Teknik',
    'S1 Sistem Informasi': 'Fakultas Teknik',
    'S1 Pendidikan Teknologi Informasi': 'Fakultas Teknik',
    'S1 Teknik Elektro': 'Fakultas Teknik',
    'S2 Informatika': 'Fakultas Teknik',
    'S2 Pendidikan Teknologi Informasi': 'Pascasarjana',
    'S1 Kecerdasan Artifisial': 'FMIPA',
    'S1 Sains Data': 'FMIPA',
    'S1 Bisnis Digital': 'FEB',
    'D4 Manajemen Informatika': 'Vokasi',
}

logger.info(f'Ontology loaded: {len(ONTOLOGY["node_types"])} node types, {len(ONTOLOGY["edge_types"])} edge types')

# ── Helper Functions ──
def md5(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]

def normalize_text(text):
    text = re.sub(r'[^\w\s]', '', str(text).lower().strip())
    return re.sub(r'\s+', ' ', text).strip()

def call_openrouter(prompt, max_retries=3):
    url = 'https://openrouter.ai/api/v1/chat/completions'
    headers = {'Authorization': f'Bearer {OPENROUTER_API_KEY}', 'Content-Type': 'application/json'}
    payload = {
        'model': LLM_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.0, 'max_tokens': 3000,
        'response_format': {'type': 'json_object'}
    }
    for attempt in range(max_retries):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=60)
            if res.status_code != 200:
                logger.warning(f'OpenRouter HTTP {res.status_code}: {res.text[:200]}')
                if attempt < max_retries - 1: time.sleep(2 ** attempt)
                continue
            content = res.json()['choices'][0]['message']['content'].strip()
            if content.startswith('```'): content = content.split('\n', 1)[1].rsplit('```', 1)[0]
            logger.debug(f'LLM response length: {len(content)} chars')
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f'LLM JSON parse error (attempt {attempt+1}): {e}')
            logger.debug(f'Raw content: {content[:300]}')
            if attempt < max_retries - 1: time.sleep(2 ** attempt)
            else: return {}
        except Exception as e:
            logger.warning(f'LLM API error (attempt {attempt+1}): {type(e).__name__}: {e}')
            if attempt < max_retries - 1: time.sleep(2 ** attempt)
            else: return {}
    return {}

# ── Load NLP models ──
logger.info('Loading spaCy en_core_web_sm...')
nlp = spacy.load('en_core_web_sm')
logger.info('Loading GLiNER urchade/gliner_multi-v2.1...')
gliner_model = GLiNER.from_pretrained('urchade/gliner_multi-v2.1', load_tokenizer=True, resize_token_embeddings=True)

end_cell('Cell 1: Setup & Ontology', {
    'Node types': len(ONTOLOGY['node_types']),
    'Edge types': len(ONTOLOGY['edge_types']),
    'NER labels': len(ONTOLOGY['ner_labels']),
    'Log file': LOG_FILE
})
