"""
Enhanced GraphRAG Retrieval — Weaviate + Neo4j
================================================
7-step pipeline with Weaviate hybrid search:
  1. Keywords VDB hybrid search → content clues
  2. LLM extracts HL + LL keywords
  3. Entity VDB hybrid search → seed entities for subgraph
  4. Neo4j subgraph traversal (2-hop) + co-author network
  5. Relationship VDB hybrid search → global context
  6. Chunk VDB hybrid search → text similarity
  7. Context fusion + LLM generation (with paper URLs)
"""
import os, json, requests, warnings, re
warnings.filterwarnings('ignore')

from neo4j import GraphDatabase
import weaviate
from weaviate.classes.query import MetadataQuery
from dotenv import load_dotenv

# ============ CONFIG ============
load_dotenv('.env')
NEO4J_URI   = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER  = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASS  = os.getenv('NEO4J_PASS', 'rizkyyk123')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
WEAVIATE_HOST = os.getenv('WEAVIATE_HOST', 'localhost')
WEAVIATE_PORT = int(os.getenv('WEAVIATE_PORT', '8081'))


def call_openrouter(prompt, json_mode=True, system_prompt=None):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": "google/gemini-2.0-flash-001", "messages": messages, "temperature": 0.3}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        content = res.json()['choices'][0]['message']['content']
        return json.loads(content) if json_mode else content
    except Exception as e:
        print(f"  LLM error: {e}")
        return {} if json_mode else ""


# ============ STEP 1: CLUE-GUIDED KEYWORD EXTRACTION ============
def step1_extract_keywords(query, wv_client):
    """Hybrid search Keywords VDB for content clues, then LLM extract HL+LL keywords."""
    col = wv_client.collections.get("ContentKeyword")
    results = col.query.hybrid(query=query, alpha=0.5, limit=5,
                                return_metadata=MetadataQuery(score=True))
    clues = [obj.properties.get('keywords', '') for obj in results.objects]
    clue_text = '; '.join(clues[:5])

    prompt = f"""Dari pertanyaan pengguna dan clue keyword berikut, ekstrak keyword pencarian.

Pertanyaan: {query}
Clue Keywords: {clue_text}

Output JSON:
{{
  "high_level_keywords": ["tema/topik umum utk pencarian global"],
  "low_level_keywords": ["entitas spesifik utk pencarian entity"],
  "vector_query": "kalimat untuk pencarian vector similarity"
}}
"""
    extracted = call_openrouter(prompt)
    return {
        'hl': extracted.get('high_level_keywords', [query]),
        'll': extracted.get('low_level_keywords', [query]),
        'vector_query': extracted.get('vector_query', query),
        'clues': clues,
    }


# ============ STEP 2: ENTITY VDB SEARCH ============
def step2_entity_search(keywords, wv_client, top_k=10):
    """Hybrid search Entity VDB using low-level keywords."""
    col = wv_client.collections.get("EntityEmbedding")
    all_results = []
    seen = set()

    for kw in keywords['ll'][:5]:
        results = col.query.hybrid(query=kw, alpha=0.5, limit=top_k,
                                    return_metadata=MetadataQuery(score=True))
        for obj in results.objects:
            nid = obj.properties.get('nodeId', '')
            if nid and nid not in seen:
                seen.add(nid)
                all_results.append({
                    'node_id': nid,
                    'name': obj.properties.get('entityName', ''),
                    'type': obj.properties.get('entityType', ''),
                    'description': obj.properties.get('description', ''),
                    'score': obj.metadata.score if obj.metadata.score else 0,
                })
    # Sort by score
    all_results.sort(key=lambda x: x['score'], reverse=True)
    return all_results[:top_k]


# ============ STEP 3: NEO4J SUBGRAPH TRAVERSAL ============
def step3_subgraph_traversal(entity_matches, neo4j_driver, hops=2):
    """2-hop traversal from matched entities in Neo4j, including co-author network."""
    context_parts = []

    with neo4j_driver.session() as session:
        for ent in entity_matches[:5]:
            nid = ent['node_id']

            # Multi-hop traversal
            result = session.run(f"""
                MATCH (start {{node_id: $nid}})
                OPTIONAL MATCH path = (start)-[r*1..{hops}]-(neighbor)
                WITH start, neighbor, r, path
                WHERE neighbor IS NOT NULL
                RETURN start.node_id as src,
                       labels(start)[0] as src_label,
                       CASE WHEN start.name IS NOT NULL THEN start.name
                            WHEN start.title IS NOT NULL THEN start.title
                            ELSE start.node_id END as src_name,
                       neighbor.node_id as tgt,
                       labels(neighbor)[0] as tgt_label,
                       CASE WHEN neighbor.name IS NOT NULL THEN neighbor.name
                            WHEN neighbor.title IS NOT NULL THEN neighbor.title
                            ELSE neighbor.node_id END as tgt_name,
                       neighbor.url as tgt_url,
                       neighbor.abstract as tgt_abstract,
                       neighbor.prodi as tgt_prodi,
                       type(last(r)) as rel_type
                LIMIT 30
            """, nid=nid)

            for record in result:
                src_name = record['src_name'] or ''
                tgt_name = record['tgt_name'] or ''
                rel = record['rel_type'] or 'RELATED'
                tgt_label = record['tgt_label'] or ''
                url = record.get('tgt_url', '') or ''
                prodi = record.get('tgt_prodi', '') or ''

                line = f"({record['src_label']}: {src_name}) -[{rel}]-> ({tgt_label}: {tgt_name})"
                if url:
                    line += f" [URL: {url}]"
                if prodi:
                    line += f" [Prodi: {prodi}]"
                context_parts.append(line)

        # Also get co-authorship info
        result = session.run("""
            MATCH (d:Dosen)-[c:COLLABORATES_WITH]->(d2:Dosen)
            WHERE c.paper_count > 1
            RETURN d.name as dosen1, d2.name as dosen2, c.paper_count as count
            ORDER BY c.paper_count DESC LIMIT 10
        """)
        collab_lines = []
        for r in result:
            collab_lines.append(f"{r['dosen1']} ↔ {r['dosen2']} ({r['count']} papers)")
        if collab_lines:
            context_parts.append("\nTop Kolaborasi Dosen:\n" + "\n".join(collab_lines))

    return list(set(context_parts))


# ============ STEP 4: RELATIONSHIP VDB SEARCH ============
def step4_relationship_search(keywords, wv_client, top_k=5):
    """Hybrid search Relationship VDB using high-level keywords → global context."""
    col = wv_client.collections.get("RelationshipEmbedding")
    all_results = []

    for kw in keywords['hl'][:3]:
        results = col.query.hybrid(query=kw, alpha=0.5, limit=top_k,
                                    return_metadata=MetadataQuery(score=True))
        for obj in results.objects:
            all_results.append(obj.properties.get('description', ''))

    return list(set(all_results))[:top_k]


# ============ STEP 5: CHUNK VDB SEARCH ============
def step5_chunk_search(keywords, wv_client, top_k=5):
    """Hybrid search Paper Chunks → text similarity context with URLs."""
    col = wv_client.collections.get("PaperChunk")
    results = col.query.hybrid(
        query=keywords['vector_query'],
        alpha=0.5, limit=top_k,
        return_metadata=MetadataQuery(score=True)
    )
    chunks = []
    for obj in results.objects:
        chunk = {
            'title': obj.properties.get('title', ''),
            'content': obj.properties.get('content', '')[:300],
            'year': obj.properties.get('year', ''),
            'authors': obj.properties.get('authors', ''),
            'url': obj.properties.get('paperUrl', ''),
            'dosen': obj.properties.get('dosenName', ''),
            'score': obj.metadata.score if obj.metadata.score else 0,
        }
        chunks.append(chunk)
    return chunks


# ============ STEP 6-7: CONTEXT FUSION + GENERATION ============
def step6_generate_answer(query, subgraph_ctx, relationship_ctx, chunks, keywords):
    """Fuse all contexts and generate answer with paper URLs."""

    # Format chunk context
    chunk_text = ""
    for i, c in enumerate(chunks[:5], 1):
        url_str = f"\n   URL: {c['url']}" if c.get('url') else ""
        chunk_text += f"\n[Paper {i}] {c['title']} ({c['year']})\n   Oleh: {c['authors'][:100]}\n   Isi: {c['content'][:200]}...{url_str}\n"

    # Format graph context
    graph_text = "\n".join(subgraph_ctx[:20]) if subgraph_ctx else "(Tidak ada konteks graph)"

    # Format relationship context
    rel_text = "\n".join(f"- {r}" for r in relationship_ctx[:5]) if relationship_ctx else "(Tidak ada)"

    system_prompt = """Anda adalah Asisten Pencarian Literatur Akademik untuk domain INFOKOM UNESA. 
Anda mirip Consensus.app dan Research Rabbit tetapi berbasis Knowledge Graph.

ATURAN:
1. Jawab dalam Bahasa Indonesia yang akademis dan terstruktur
2. SELALU cantumkan nama dosen, judul paper, tahun, dan URL jika tersedia
3. Gunakan format yang mudah dibaca dengan bullet points
4. Jika informasi tidak ada, katakan dengan jujur
5. Hubungkan antar konsep jika relevan (co-authorship, metode yang sama, dll)
6. Berikan insight dari knowledge graph (mis. dosen X sering berkolaborasi dengan Y)
"""

    prompt = f"""PERTANYAAN: {query}

=== KONTEKS GRAPH (Neo4j Subgraph) ===
{graph_text}

=== KONTEKS RELASI GLOBAL ===
{rel_text}

=== PAPER RELEVAN (Weaviate Hybrid Search) ===
{chunk_text}

=== KEYWORD PENCARIAN ===
High-level: {keywords['hl']}
Low-level: {keywords['ll']}

Berikan jawaban komprehensif berdasarkan semua konteks di atas. 
Selalu cantumkan referensi paper (judul, tahun, URL jika ada).
"""

    return call_openrouter(prompt, json_mode=False, system_prompt=system_prompt)


# ============ MAIN QUERY FUNCTION ============
def hybrid_graphrag_query(question):
    """Full 7-step Hybrid GraphRAG Query."""
    print("=" * 70)
    print(f"PERTANYAAN: {question}")
    print("=" * 70)

    # Connect
    wv = weaviate.connect_to_local(host=WEAVIATE_HOST, port=WEAVIATE_PORT)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    try:
        # Step 1: Keyword extraction
        print("\n[Step 1] Extracting keywords (hybrid clue-guided)...")
        keywords = step1_extract_keywords(question, wv)
        print(f"  HL Keywords: {keywords['hl']}")
        print(f"  LL Keywords: {keywords['ll']}")
        print(f"  Vector Query: {keywords['vector_query']}")

        # Step 2: Entity search
        print("\n[Step 2] Entity VDB Hybrid Search...")
        entities = step2_entity_search(keywords, wv)
        for e in entities[:5]:
            print(f"  [{e['type']}] {e['name']} (score: {e['score']:.3f})")

        # Step 3: Subgraph traversal
        print("\n[Step 3] Neo4j Subgraph Traversal (2-hop)...")
        subgraph_ctx = step3_subgraph_traversal(entities, driver)
        print(f"  Found {len(subgraph_ctx)} context items")

        # Step 4: Relationship search
        print("\n[Step 4] Relationship VDB Hybrid Search...")
        rel_ctx = step4_relationship_search(keywords, wv)
        print(f"  Found {len(rel_ctx)} relationship contexts")

        # Step 5: Chunk search
        print("\n[Step 5] Chunk VDB Hybrid Search...")
        chunks = step5_chunk_search(keywords, wv)
        for c in chunks[:3]:
            title_short = c['title'][:60]
            print(f"  [{c['score']:.3f}] {title_short}...")

        # Step 6-7: Fusion + Generation
        print("\n[Step 6-7] Context Fusion + Answer Generation...")
        answer = step6_generate_answer(question, subgraph_ctx, rel_ctx, chunks, keywords)

        print("\n" + "=" * 70)
        print("JAWABAN:")
        print(answer)
        print("=" * 70)
        return answer

    finally:
        wv.close()
        driver.close()


# ============ TESTING ============
if __name__ == "__main__":
    # Test queries
    test_queries = [
        "Siapa dosen yang meneliti tentang deep learning atau machine learning?",
        "Apa saja metode penelitian yang digunakan dosen Teknik Informatika?",
        "Paper apa yang membahas tentang aplikasi web atau sistem informasi?",
    ]

    for q in test_queries:
        hybrid_graphrag_query(q)
        print("\n\n")
