"""Offline community detection and summarization script for Yunesa GraphRAG.

This module performs:
1. Graph projection and Louvain clustering using Neo4j GDS.
2. Grouping nodes by community and generating Indonesian executive summaries using DeepSeek.
3. Writing summaries back to Neo4j on :Community nodes.
4. Embedding summaries using SiliconFlow and indexing them into Milvus.
"""

import os
import re
import sys
import time
import requests
from typing import Any, Dict, List
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pymilvus import MilvusClient, DataType, FieldSchema, CollectionSchema

# Load environment variables
load_dotenv()

# Logger helper
def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def get_neo4j_driver():
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not password:
        raise ValueError("NEO4J_URI or NEO4J_PASSWORD not found in environment.")
    return GraphDatabase.driver(uri, auth=(username, password))

def get_milvus_client():
    uri = os.getenv("MILVUS_URI")
    token = os.getenv("MILVUS_TOKEN")
    db_name = os.getenv("MILVUS_DB_NAME", "default")
    if not uri:
        raise ValueError("MILVUS_URI not found in environment.")
    client = MilvusClient(uri=uri, token=token)
    try:
        # Check if database usage is supported on this client
        if db_name and hasattr(client, "using_database"):
            client.using_database(db_name)
    except Exception as e:
        log(f"Warning setting database: {e}")
    return client

def run_gds_louvain():
    log("Starting Neo4j GDS Louvain clustering...")
    driver = get_neo4j_driver()
    db_name = os.getenv("NEO4J_DATABASE", "neo4j")
    
    with driver.session(database=db_name) as session:
        # 1. Clean up old projection if exists
        log("Cleaning up old GDS graph projection if exists...")
        session.run("CALL gds.graph.drop('academic_graph', false)")
        
        # 2. Project Graph
        log("Creating new GDS graph projection for all nodes and relationships...")
        project_query = """
        CALL gds.graph.project(
            'academic_graph',
            ['Lecturer', 'Publication', 'Concept', 'Keyword', 'Venue', 'Year'],
            ['PUBLISHES', 'HAS_AUTHOR', 'HAS_TOPIC', 'HAS_KEYWORD', 'PUBLISHED_IN_VENUE', 'PUBLISHED_IN_YEAR'],
            { memory: '2GB' }
        )
        """
        session.run(project_query)
        
        # 3. Run Louvain and write back communityId
        log("Running Louvain community detection...")
        # Note: on AuraDS, write procedures also require GDS session parameters in some versions
        # Let's pass the GDS session config map if needed
        result = session.run("CALL gds.louvain.write('academic_graph', { writeProperty: 'communityId' })")
        record = result.single()
        if record:
            log(f"Louvain completed. Write count: {record.get('nodePropertiesWritten', 0)}")
            log(f"Modularity: {record.get('modularity', 0.0):.4f}, Communities: {record.get('communityCount', 0)}")
            
        # Clean up projection
        log("Dropping GDS projection...")
        session.run("CALL gds.graph.drop('academic_graph', false)")
        
    driver.close()

def fetch_communities() -> Dict[int, List[Dict[str, Any]]]:
    log("Fetching clustered nodes from Neo4j...")
    driver = get_neo4j_driver()
    db_name = os.getenv("NEO4J_DATABASE", "neo4j")
    
    query = """
    MATCH (n)
    WHERE n.communityId IS NOT NULL
    RETURN n.communityId AS communityId, 
           labels(n)[0] AS type, 
           coalesce(n.name, n.title, n.displayName, '') AS name
    """
    
    communities = {}
    with driver.session(database=db_name) as session:
        result = session.run(query)
        for record in result:
            cid = int(record["communityId"])
            node = {
                "type": record["type"],
                "name": record["name"]
            }
            if cid not in communities:
                communities[cid] = []
            communities[cid].append(node)
            
    driver.close()
    log(f"Fetched {len(communities)} communities.")
    return communities

def generate_summary_with_deepseek(community_id: int, nodes: List[Dict[str, Any]]) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is missing.")
        
    # Group nodes by type to create a clean text list
    grouped = {}
    for node in nodes:
        ntype = node["type"]
        if ntype not in grouped:
            grouped[ntype] = []
        grouped[ntype].append(node["name"])
        
    # Prepare details string
    details = []
    for ntype, names in grouped.items():
        unique_names = list(set(names))[:30]  # Cap at 30 items per type to keep prompt compact
        details.append(f"- **{ntype}**: {', '.join(unique_names)}")
    details_str = "\n".join(details)
    
    prompt = f"""Anda adalah seorang peneliti dan analis akademik. Tugas Anda adalah menulis ringkasan eksekutif akademis (executive summary) yang terstruktur dan padat dalam Bahasa Indonesia untuk sebuah komunitas akademik (Komunitas ID: {community_id}).

Komunitas ini berisi entitas berikut:
{details_str}

Berdasarkan data di atas, tulis ringkasan deskriptif sepanjang 1-2 paragraf yang menjelaskan:
1. Fokus bidang penelitian utama dari komunitas ini.
2. Siapa saja dosen/peneliti kunci di dalamnya beserta topik utama yang mereka publikasikan.
3. Keterkaitan konsep dan kata kunci yang mendominasi klaster ini.

Tuliskan ringkasan Anda secara langsung, objektif, dan akademis. Jangan berikan teks pembuka atau penutup bawaan AI."""

    log(f"Generating summary for Community {community_id} (contains {len(nodes)} nodes)...")
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a professional academic research assistant."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            },
            timeout=30.0
        )
        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"].strip()
        return summary
    except Exception as e:
        log(f"Failed to generate summary for Community {community_id}: {e}")
        return ""

def write_summaries_to_neo4j(summaries: Dict[int, str]):
    log("Writing community summaries and relationships to Neo4j...")
    driver = get_neo4j_driver()
    db_name = os.getenv("NEO4J_DATABASE", "neo4j")
    
    with driver.session(database=db_name) as session:
        for cid, summary in summaries.items():
            if not summary:
                continue
            
            # Create Community node
            session.run(
                """
                MERGE (c:Community {id: $cid})
                SET c.summary = $summary
                """,
                cid=cid,
                summary=summary
            )
            
            # Link members of the community
            session.run(
                """
                MATCH (n)
                WHERE n.communityId = $cid
                MATCH (c:Community {id: $cid})
                MERGE (n)-[:BELONGS_TO_COMMUNITY]->(c)
                """,
                cid=cid
            )
    driver.close()
    log("Neo4j writing completed.")

def embed_texts(texts: List[str]) -> List[List[float]]:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise ValueError("SILICONFLOW_API_KEY is missing.")
        
    log(f"Generating embeddings for {len(texts)} summaries via SiliconFlow...")
    try:
        response = requests.post(
            "https://api.siliconflow.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "Qwen/Qwen3-Embedding-0.6B",
                "input": texts
            },
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json().get("data") or []
        # Sort by index to maintain original order
        sorted_data = sorted(data, key=lambda x: x.get("index", 0))
        embeddings = [item["embedding"] for item in sorted_data]
        return embeddings
    except Exception as e:
        log(f"Failed to generate embeddings: {e}")
        raise

def setup_milvus_collection(client: MilvusClient):
    collection_name = "community_summaries"
    log(f"Setting up Milvus collection: {collection_name}")
    
    if client.has_collection(collection_name):
        log(f"Collection {collection_name} already exists. Re-creating to update schema...")
        client.drop_collection(collection_name)
        
    schema = CollectionSchema(
        fields=[
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
            FieldSchema(name="graphName", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="community_id", dtype=DataType.INT64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024)
        ],
        description="Global GraphRAG community summaries collection"
    )
    
    client.create_collection(
        collection_name=collection_name,
        schema=schema
    )
    
    # Create vector index correctly using prepare_index_params
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        metric_type="L2",
        index_type="FLAT"
    )
    client.create_index(
        collection_name=collection_name,
        index_params=index_params
    )
    log(f"Created collection {collection_name} and index successfully.")

def index_summaries_in_milvus(summaries: Dict[int, str]):
    client = get_milvus_client()
    setup_milvus_collection(client)
    
    cids = []
    texts = []
    for cid, summary in summaries.items():
        if summary:
            cids.append(cid)
            texts.append(summary)
            
    if not texts:
        log("No summaries to index in Milvus.")
        return
        
    embeddings = embed_texts(texts)
    
    graph_name = os.getenv("NEO4J_DATABASE") or "yunesa_academic_kg"
    data = []
    for i, cid in enumerate(cids):
        data.append({
            "id": f"community_{cid}",
            "graphName": graph_name,
            "community_id": cid,
            "content": texts[i],
            "embedding": embeddings[i]
        })
        
    log("Inserting summaries into Milvus...")
    client.insert(collection_name="community_summaries", data=data)
    log("Loading collection into memory...")
    client.load_collection("community_summaries")
    log("Milvus insertion and loading completed successfully.")

def main():
    log("--- Starting GraphRAG Offline Community Summarization Pipeline ---")
    try:
        # Step 1: Run Louvain clustering
        run_gds_louvain()
        
        # Step 2: Fetch communities
        communities = fetch_communities()
        if not communities:
            log("No communities found to summarize. Exiting.")
            return
            
        # Step 3: Summarize each community using DeepSeek
        summaries = {}
        for cid, nodes in communities.items():
            # Skip communities that are too small (e.g. single nodes) to keep summaries meaningful
            if len(nodes) < 3:
                continue
            summary = generate_summary_with_deepseek(cid, nodes)
            summaries[cid] = summary
            # Polite rate-limiting sleep
            time.sleep(0.5)
            
        # Step 4: Save summaries back to Neo4j
        write_summaries_to_neo4j(summaries)
        
        # Step 5: Embed and save to Milvus
        index_summaries_in_milvus(summaries)
        
        log("--- Pipeline completed successfully! ---")
        
    except Exception as e:
        log(f"Error in pipeline execution: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
