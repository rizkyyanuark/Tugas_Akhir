"""
Enhanced KG Construction Pipeline — Weaviate + Neo4j
=====================================================
Full ontology matching LaTeX design (14+ node types):
  Metadata:  Paper, Dosen, ProgramStudi, Fakultas, Journal, Year, Keyword, Field
  Concepts:  Problem, Method, Metric, Dataset, Task, Model, Results, Innovation

Features:
  - Weaviate Hybrid Search (BM25 + Vector via text2vec-transformers)
  - Scholar-ID based author resolution (no duplicates)
  - ProgramStudi → Fakultas hierarchy
  - Paper URL/Link stored for assistant answers
  - Co-authorship network (COLLABORATES_WITH)
  - Entity dedup via normalized names
"""
import pandas as pd
import json, os, requests, time, warnings, hashlib, re
from collections import defaultdict
warnings.filterwarnings('ignore')

from neo4j import GraphDatabase
import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.data import DataObject
from dotenv import load_dotenv

# ============ CONFIG ============
load_dotenv('.env')
NEO4J_URI   = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER  = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASS  = os.getenv('NEO4J_PASS', 'rizkyyk123')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
WEAVIATE_HOST = os.getenv('WEAVIATE_HOST', 'localhost')
WEAVIATE_PORT = int(os.getenv('WEAVIATE_PORT', '8081'))

# Mapping ProgramStudi → Fakultas
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

CONCEPT_LABELS = ['Problem', 'Method', 'Task', 'Dataset', 'Model', 'Metric',
                  'Technology', 'Field', 'Results', 'Innovation']

def md5(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]

def normalize_text(text):
    """Normalize for dedup: lowercase, strip, collapse spaces."""
    text = re.sub(r'[^\w\s]', '', str(text).lower().strip())
    return re.sub(r'\s+', ' ', text).strip()

def call_openrouter(prompt, json_mode=True):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        content = res.json()['choices'][0]['message']['content']
        return json.loads(content) if json_mode else content
    except Exception as e:
        print(f"  OpenRouter error: {e}")
        return {} if json_mode else ""


def extract_scientific_concepts(abstract, title=""):
    """Extract full ontology concepts from abstract using LLM."""
    prompt = f"""Anda adalah ekstractor Knowledge Graph untuk literatur akademik. 
Dari abstrak penelitian berikut, ekstrak konsep-konsep ilmiah:

1. **problem** — masalah yang diteliti (1-3 items)
2. **method** — metode/algoritma yang digunakan (1-5 items)
3. **task** — tugas utama penelitian, mis. "klasifikasi", "prediksi" (1-3 items)
4. **dataset** — dataset yang digunakan jika disebutkan (0-3 items)
5. **model** — model spesifik yang diajukan/digunakan (0-3 items)
6. **metric** — metrik evaluasi, mis. "akurasi", "F1-score" (0-3 items)
7. **results** — hasil ringkas utama, mis. "akurasi 95%" (0-2 items)
8. **innovation** — kontribusi/inovasi unik paper ini (0-2 items)
9. **field** — bidang ilmu, mis. "machine learning", "NLP", "IoT" (1-3 items)

Setiap item harus punya: "text" dan "description" (1 kalimat konteks)

10. **relations** — hubungan antar-konsep (subject, relation, object, description)
    Tipe relasi: solves, adopts, uses, proposes, has, works_on, experiments_on, innovates, evaluated_by, faces
11. **content_keywords** — 5-10 keyword penting

Output JSON:
{{
  "problem": [{{"text": "...", "description": "..."}}],
  "method": [{{"text": "...", "description": "..."}}],
  "task": [{{"text": "...", "description": "..."}}],
  "dataset": [{{"text": "...", "description": "..."}}],
  "model": [{{"text": "...", "description": "..."}}],
  "metric": [{{"text": "...", "description": "..."}}],
  "results": [{{"text": "...", "description": "..."}}],
  "innovation": [{{"text": "...", "description": "..."}}],
  "field": [{{"text": "...", "description": "..."}}],
  "relations": [{{"subject": "...", "relation": "...", "object": "...", "description": "..."}}],
  "content_keywords": ["keyword1", "keyword2"]
}}

Judul: {title}
Abstrak: {abstract[:2500]}
"""
    return call_openrouter(prompt)


# ============ WEAVIATE SETUP ============
def setup_weaviate():
    """Connect to Weaviate and create classes."""
    print(f"Connecting to Weaviate at {WEAVIATE_HOST}:{WEAVIATE_PORT}...")
    client = weaviate.connect_to_local(host=WEAVIATE_HOST, port=WEAVIATE_PORT)
    assert client.is_ready(), "Weaviate is not ready!"
    print("  ✅ Weaviate connected")

    # Define 4 classes with text2vec-transformers auto-vectorizer
    classes_config = {
        "EntityEmbedding": [
            Property(name="entityName", data_type=DataType.TEXT),
            Property(name="entityType", data_type=DataType.TEXT),
            Property(name="description", data_type=DataType.TEXT),
            Property(name="sourcePapers", data_type=DataType.TEXT),
            Property(name="nodeId", data_type=DataType.TEXT),
        ],
        "RelationshipEmbedding": [
            Property(name="srcId", data_type=DataType.TEXT),
            Property(name="tgtId", data_type=DataType.TEXT),
            Property(name="relType", data_type=DataType.TEXT),
            Property(name="keywords", data_type=DataType.TEXT),
            Property(name="description", data_type=DataType.TEXT),
        ],
        "ContentKeyword": [
            Property(name="keywords", data_type=DataType.TEXT),
            Property(name="sourcePaper", data_type=DataType.TEXT),
        ],
        "PaperChunk": [
            Property(name="title", data_type=DataType.TEXT),
            Property(name="content", data_type=DataType.TEXT),
            Property(name="year", data_type=DataType.TEXT),
            Property(name="authors", data_type=DataType.TEXT),
            Property(name="paperUrl", data_type=DataType.TEXT),
            Property(name="dosenName", data_type=DataType.TEXT),
        ],
    }

    for class_name, props in classes_config.items():
        if client.collections.exists(class_name):
            client.collections.delete(class_name)
            print(f"  Deleted old '{class_name}'")
        client.collections.create(
            name=class_name,
            vectorizer_config=Configure.Vectorizer.text2vec_transformers(),
            properties=props,
        )
        print(f"  ✅ Created '{class_name}'")

    return client


# ============ NEO4J INGESTION ============
def ingest_neo4j(nodes, edges):
    """Ingest nodes and edges into Neo4j."""
    print(f"\nIngesting {len(nodes)} nodes and {len(edges)} edges into Neo4j...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    with driver.session() as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph")

        # Create constraints for faster MERGE
        for label in ['Paper', 'Dosen', 'ProgramStudi', 'Fakultas', 'Journal', 'Year',
                      'Keyword', 'Problem', 'Method', 'Task', 'Dataset', 'Model',
                      'Metric', 'Results', 'Innovation', 'Field', 'ExternalAuthor']:
            try:
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.node_id IS UNIQUE")
            except:
                pass

        # Insert nodes
        for node_id, data in nodes.items():
            label = data.get('_label', 'Entity')
            props = {k: v for k, v in data.items() if k != '_label' and v}
            props['node_id'] = node_id
            set_clause = ', '.join([f"n.`{k}` = ${k}" for k in props])
            session.run(f"MERGE (n:{label} {{node_id: $node_id}}) SET {set_clause}", **props)

        print(f"  ✅ Nodes inserted: {len(nodes)}")

        # Insert edges
        for src, tgt, rel_type, props in edges:
            src_label = nodes.get(src, {}).get('_label', 'Entity')
            tgt_label = nodes.get(tgt, {}).get('_label', 'Entity')
            safe_rel = re.sub(r'[^A-Z_]', '_', rel_type.upper())
            prop_set = ""
            if props:
                prop_parts = ', '.join([f"r.`{k}` = ${k}" for k in props])
                prop_set = f" SET {prop_parts}"
            session.run(
                f"MATCH (a:{src_label} {{node_id: $src}}) "
                f"MATCH (b:{tgt_label} {{node_id: $tgt}}) "
                f"MERGE (a)-[r:{safe_rel}]->(b){prop_set}",
                src=src, tgt=tgt, **props
            )

        print(f"  ✅ Edges inserted: {len(edges)}")

        # Build co-authorship network (no APOC required)
        print("  Building COLLABORATES_WITH network...")
        try:
            result = session.run("""
                MATCH (a:Dosen)-[:WRITES]->(p:Paper)<-[:WRITES]-(b:Dosen)
                WHERE a.node_id < b.node_id
                WITH a, b, count(p) as collab_count
                MERGE (a)-[r:COLLABORATES_WITH]->(b)
                SET r.paper_count = collab_count
                RETURN count(r) as total
            """)
            collab_count = result.single()['total']
            print(f"  ✅ Co-authorship edges: {collab_count}")
        except Exception as e:
            print(f"  ⚠️ COLLABORATES_WITH skipped: {e}")

    driver.close()
    print("  ✅ Neo4j ingestion complete")


# ============ MAIN PIPELINE ============
def main():
    print("=" * 70)
    print("ENHANCED KG CONSTRUCTION — Weaviate + Neo4j Full Ontology")
    print("=" * 70)

    # 1. Load Data
    print("\n[1/5] Loading data...")
    df_papers = pd.read_csv(
        r'C:\Users\rizky_11yf1be\Desktop\Tugas_Akhir\notebooks\scraping\file_tabulars\dosen_papers_scholar_colab.csv'
    ).fillna('')
    df_dosen = pd.read_csv(
        r'C:\Users\rizky_11yf1be\Desktop\Tugas_Akhir\notebooks\scraping\file_tabulars\dosen_infokom_final.csv'
    ).fillna('')

    # Filter papers with abstracts, take 50 for testing
    df_sample = df_papers[df_papers['Abstract'].str.len() > 30].head(50).copy()
    print(f"  Total papers: {len(df_papers)}, with abstracts: {(df_papers['Abstract'].str.len()>30).sum()}")
    print(f"  Testing with: {len(df_sample)} papers")

    # Build dosen lookup by scholar_id
    dosen_lookup = {}
    for _, row in df_dosen.iterrows():
        sid = str(row.get('scholar_id', '')).strip()
        if sid and sid not in ('nan', 'None', ''):
            dosen_lookup[sid] = row.to_dict()

    # 2. Build KG Data Structures
    print("\n[2/5] Building Knowledge Graph structures...")
    nodes = {}   # node_id -> {_label, prop1, prop2, ...}
    edges = []   # (src, tgt, rel_type, {props})

    # VDB accumulators
    entity_vdb = []
    relationship_vdb = []
    keywords_vdb = []
    chunk_vdb = []

    # ── Build structural nodes first (Fakultas, ProgramStudi, Dosen) ──
    fakultas_set = set()
    prodi_set = set()
    for _, row in df_dosen.iterrows():
        prodi = str(row.get('prodi', '')).strip()
        fak = PRODI_FAKULTAS.get(prodi, 'Fakultas Teknik')
        sid = str(row.get('scholar_id', '')).strip()
        if sid in ('nan', 'None', ''):
            sid = ''

        # Fakultas
        fak_id = f"fak_{normalize_text(fak).replace(' ', '_')}"
        if fak_id not in nodes:
            nodes[fak_id] = {'_label': 'Fakultas', 'name': fak}
            fakultas_set.add(fak_id)

        # ProgramStudi
        prodi_id = f"prodi_{normalize_text(prodi).replace(' ', '_')}"
        if prodi_id not in nodes:
            nodes[prodi_id] = {'_label': 'ProgramStudi', 'name': prodi}
            edges.append((prodi_id, fak_id, 'PART_OF', {}))
            prodi_set.add(prodi_id)

        # Dosen
        dosen_id = f"dosen_{sid}" if sid else f"dosen_{normalize_text(row['nama_norm']).replace(' ', '_')}"
        if dosen_id not in nodes:
            nodes[dosen_id] = {
                '_label': 'Dosen',
                'name': row.get('nama_norm', row['nama_dosen']),
                'scholar_id': sid,
                'scopus_id': str(row.get('scopus_id', '')),
                'nidn': str(row.get('nidn', '')),
                'nip': str(row.get('nip', '')),
                'jafung': str(row.get('jafung', '')),
                'gelar': str(row.get('gelar', '')),
                'prodi': prodi,
            }
            edges.append((dosen_id, prodi_id, 'MEMBER_OF', {}))

            # Dosen entity for VDB
            entity_vdb.append({
                'nodeId': dosen_id,
                'entityName': row.get('nama_norm', row['nama_dosen']),
                'entityType': 'Dosen',
                'description': f"{row.get('nama_norm', '')} adalah dosen prodi {prodi} di UNESA. {row.get('jafung', '')}",
                'sourcePapers': '',
            })

    print(f"  Structural: {len(fakultas_set)} fakultas, {len(prodi_set)} prodi, "
          f"{sum(1 for v in nodes.values() if v['_label']=='Dosen')} dosen")

    # ── Process papers ──
    entity_dedup = {}  # normalized_name -> node_id (for concept dedup)
    journal_set = set()
    year_set = set()

    print("\n[3/5] Processing papers with LLM extraction...")
    for paper_idx, (idx, row) in enumerate(df_sample.iterrows()):
        title = str(row['Title']).strip()
        abstract = str(row['Abstract']).strip()
        authors_raw = str(row['Authors']).strip()
        year = str(row['Year']).strip()[:4]
        journal = str(row['Journal']).strip()
        doi = str(row['DOI']).strip()
        link = str(row.get('Link', '')).strip()
        dosen_name = str(row.get('dosen', '')).strip()
        paper_sid = str(row.get('scholar_id', '')).strip()
        keywords_raw = str(row.get('Keywords', '')).strip()
        tldr = str(row.get('TLDR', '')).strip()
        doc_type = str(row.get('Document Type', '')).strip()

        paper_id = f"paper_{md5(title)}"
        print(f"\n[{paper_idx+1}/50] {title[:60]}...")

        # ── Paper Node ──
        nodes[paper_id] = {
            '_label': 'Paper', 'title': title, 'year': year,
            'doi': doi, 'url': link, 'abstract': abstract[:500],
            'tldr': tldr[:300], 'doc_type': doc_type or 'Article',
            'journal': journal,
        }

        # ── Journal Node ──
        if journal and journal not in ('nan', 'None', ''):
            j_id = f"journal_{md5(journal)}"
            if j_id not in nodes:
                nodes[j_id] = {'_label': 'Journal', 'name': journal}
                journal_set.add(j_id)
            edges.append((paper_id, j_id, 'PUBLISHED_IN', {}))

        # ── Year Node ──
        if year and year.isdigit():
            y_id = f"year_{year}"
            if y_id not in nodes:
                nodes[y_id] = {'_label': 'Year', 'value': year}
                year_set.add(y_id)
            edges.append((paper_id, y_id, 'PUBLISHED_YEAR', {}))

        # ── Author Resolution (Scholar-ID based) ──
        authors = [a.strip() for a in authors_raw.split(',') if a.strip()]
        author_ids = [a.strip() for a in str(row.get('Author IDs', '')).split(';') if a.strip()]

        for i, author_name in enumerate(authors):
            aid_raw = author_ids[i] if i < len(author_ids) else ''

            # Try to resolve to UNESA Dosen
            if aid_raw and aid_raw in dosen_lookup:
                dosen_id = f"dosen_{aid_raw}"
                edges.append((dosen_id, paper_id, 'WRITES', {'position': 'first' if i == 0 else 'co-author'}))
            elif paper_sid and paper_sid in dosen_lookup and i == 0:
                dosen_id = f"dosen_{paper_sid}"
                edges.append((dosen_id, paper_id, 'WRITES', {'position': 'first'}))
            else:
                # External author (not in UNESA DB)
                ext_id = f"ext_{normalize_text(author_name).replace(' ', '_')}"
                if ext_id not in nodes:
                    nodes[ext_id] = {'_label': 'ExternalAuthor', 'name': author_name}
                edges.append((ext_id, paper_id, 'WRITES', {'position': 'first' if i == 0 else 'co-author'}))

        # ── Keyword Nodes (from CSV) ──
        if keywords_raw and keywords_raw not in ('nan', 'None'):
            for kw in re.split(r'[;,]', keywords_raw):
                kw = kw.strip()
                if kw and len(kw) > 2:
                    kw_norm = normalize_text(kw)
                    kw_id = f"kw_{md5(kw_norm)}"
                    if kw_id not in nodes:
                        nodes[kw_id] = {'_label': 'Keyword', 'text': kw, 'normalized': kw_norm}
                    edges.append((paper_id, kw_id, 'HAS_KEYWORD', {}))

        # ── Chunk VDB ──
        chunk_vdb.append({
            'title': title,
            'content': f"{title}. {abstract[:2000]}",
            'year': year,
            'authors': authors_raw[:200],
            'paperUrl': link,
            'dosenName': dosen_name,
        })

        # ── LLM Extraction (scientific concepts) ──
        if abstract and len(abstract) > 50:
            extracted = extract_scientific_concepts(abstract[:2500], title)

            # Process each concept type
            for concept_type in ['problem', 'method', 'task', 'dataset', 'model',
                                 'metric', 'results', 'innovation', 'field']:
                items = extracted.get(concept_type, [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get('text', '')).strip()
                    desc = str(item.get('description', '')).strip()
                    if not text or len(text) < 2:
                        continue

                    label = concept_type.capitalize()
                    norm = normalize_text(text)

                    # Entity dedup: check if similar entity exists
                    if norm in entity_dedup:
                        eid = entity_dedup[norm]
                        # Append description
                        if desc and desc not in nodes.get(eid, {}).get('description', ''):
                            nodes[eid]['description'] = (nodes[eid].get('description', '') + ' ' + desc)[:500]
                    else:
                        eid = f"{concept_type}_{md5(norm)}"
                        nodes[eid] = {'_label': label, 'name': text, 'description': desc}
                        entity_dedup[norm] = eid

                    # Edge: Paper → Concept
                    rel_map = {
                        'problem': 'SOLVES', 'method': 'ADOPTS', 'task': 'WORKS_ON',
                        'dataset': 'EXPERIMENTS_ON', 'model': 'PROPOSES', 'metric': 'USES_METRIC',
                        'results': 'HAS_RESULTS', 'innovation': 'INNOVATES', 'field': 'BELONGS_TO',
                    }
                    edges.append((paper_id, eid, rel_map.get(concept_type, 'MENTIONS'), {'description': desc[:200]}))

                    # Entity VDB
                    entity_vdb.append({
                        'nodeId': eid,
                        'entityName': text,
                        'entityType': label,
                        'description': desc,
                        'sourcePapers': paper_id,
                    })

            # Process inter-concept relations
            for rel in extracted.get('relations', []):
                if not isinstance(rel, dict):
                    continue
                subj = normalize_text(str(rel.get('subject', '')))
                obj = normalize_text(str(rel.get('object', '')))
                rel_type = str(rel.get('relation', 'related')).upper().replace(' ', '_')
                rel_desc = str(rel.get('description', ''))

                if subj in entity_dedup and obj in entity_dedup:
                    src_id = entity_dedup[subj]
                    tgt_id = entity_dedup[obj]
                    edges.append((src_id, tgt_id, rel_type, {'description': rel_desc[:200]}))

                    relationship_vdb.append({
                        'srcId': src_id, 'tgtId': tgt_id,
                        'relType': rel_type,
                        'keywords': f"{subj}, {obj}",
                        'description': rel_desc,
                    })

            # Content keywords
            content_kw = extracted.get('content_keywords', [])
            if isinstance(content_kw, list) and content_kw:
                keywords_vdb.append({
                    'keywords': ', '.join(str(k) for k in content_kw),
                    'sourcePaper': paper_id,
                })

            time.sleep(0.5)  # Rate limit

    # ── Summary ──
    label_counts = defaultdict(int)
    for v in nodes.values():
        label_counts[v['_label']] += 1
    print(f"\n{'='*60}")
    print("GRAPH SUMMARY:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"  {label:20s}: {count}")
    print(f"  {'TOTAL NODES':20s}: {len(nodes)}")
    print(f"  {'TOTAL EDGES':20s}: {len(edges)}")
    print(f"  Entity VDB entries : {len(entity_vdb)}")
    print(f"  Relationship VDB   : {len(relationship_vdb)}")
    print(f"  Keywords VDB       : {len(keywords_vdb)}")
    print(f"  Chunk VDB          : {len(chunk_vdb)}")
    print(f"{'='*60}")

    # 4. Neo4j Ingestion
    print("\n[4/5] Neo4j Ingestion...")
    ingest_neo4j(nodes, edges)

    # 5. Weaviate Ingestion
    print("\n[5/5] Weaviate Ingestion...")
    wv = setup_weaviate()
    time.sleep(3)  # Wait for schema to be fully committed

    def weaviate_batch_insert(collection_name, data_list, batch_size=20):
        """Insert data into Weaviate in small batches with error handling."""
        col = wv.collections.get(collection_name)
        total = 0
        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            try:
                col.data.insert_many([DataObject(properties=item) for item in batch])
                total += len(batch)
            except Exception as e:
                print(f"    ⚠️ Batch {i//batch_size} error: {e}")
                # Try one-by-one fallback
                for item in batch:
                    try:
                        col.data.insert(item)
                        total += 1
                    except Exception as e2:
                        print(f"    ❌ Skip item: {e2}")
            time.sleep(0.5)  # Brief pause between batches
        return total

    count = weaviate_batch_insert("EntityEmbedding", entity_vdb)
    print(f"  EntityEmbedding: {count}/{len(entity_vdb)} entries")

    count = weaviate_batch_insert("RelationshipEmbedding", relationship_vdb)
    print(f"  RelationshipEmbedding: {count}/{len(relationship_vdb)} entries")

    count = weaviate_batch_insert("ContentKeyword", keywords_vdb)
    print(f"  ContentKeyword: {count}/{len(keywords_vdb)} entries")

    count = weaviate_batch_insert("PaperChunk", chunk_vdb)
    print(f"  PaperChunk: {count}/{len(chunk_vdb)} entries")

    wv.close()

    print("\n" + "=" * 70)
    print("✅ PIPELINE COMPLETE — Weaviate + Neo4j Full Ontology Ready!")
    print("=" * 70)


if __name__ == "__main__":
    main()
