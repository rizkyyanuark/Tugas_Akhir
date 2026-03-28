# ══════════════════════════════════════════════════════════════════════
# CELL 7: Database Ingestion (Neo4j + Weaviate)
# ══════════════════════════════════════════════════════════════════════
start_cell('Cell 7: Database Ingestion')

# Weaviate
logger.info(f'Connecting to Weaviate at {WEAVIATE_HOST}:{WEAVIATE_PORT}...')
wv_client = weaviate.connect_to_local(host=WEAVIATE_HOST, port=WEAVIATE_PORT)
logger.info('Weaviate connected.')

classes_config = {
    'EntityEmbedding': [Property(name='entityName', data_type=DataType.TEXT), Property(name='entityType', data_type=DataType.TEXT), Property(name='description', data_type=DataType.TEXT), Property(name='nodeId', data_type=DataType.TEXT)],
    'RelationshipEmbedding': [Property(name='srcId', data_type=DataType.TEXT), Property(name='tgtId', data_type=DataType.TEXT), Property(name='relType', data_type=DataType.TEXT), Property(name='description', data_type=DataType.TEXT)],
    'ContentKeyword': [Property(name='keywords', data_type=DataType.TEXT), Property(name='sourcePaper', data_type=DataType.TEXT)],
    'PaperChunk': [Property(name='title', data_type=DataType.TEXT), Property(name='content', data_type=DataType.TEXT), Property(name='year', data_type=DataType.TEXT), Property(name='paperUrl', data_type=DataType.TEXT)],
}
for c, props in classes_config.items():
    if wv_client.collections.exists(c):
        wv_client.collections.delete(c)
        logger.info(f'  Deleted existing Weaviate collection: {c}')
    wv_client.collections.create(name=c, vectorizer_config=Configure.Vectorizer.text2vec_transformers(), properties=props)
    logger.info(f'  Created Weaviate collection: {c}')

# Neo4j
logger.info(f'Connecting to Neo4j at {NEO4J_URI}...')
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
ALL_LABELS = list(ONTOLOGY['node_types'].keys())
with driver.session() as s:
    s.run('MATCH (n) DETACH DELETE n')
    logger.info('  Neo4j: all existing data deleted')
    for lbl in ALL_LABELS:
        s.run(f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.node_id IS UNIQUE')
    logger.info(f'  Neo4j: {len(ALL_LABELS)} uniqueness constraints created')

# Neo4j: nodes
logger.info(f'Ingesting {len(nodes)} nodes to Neo4j...')
node_errors = 0
t0 = time.time()
with driver.session() as s:
    for nid, d in nodes.items():
        try:
            lbl = d['_label']
            props = {k: str(v) for k, v in d.items() if k != '_label' and v and str(v) != 'nan'}
            props['node_id'] = nid
            sc = ', '.join([f'n.`{k}` = ${k}' for k in props])
            s.run(f'MERGE (n:{lbl} {{node_id: $node_id}}) SET {sc}', **props)
        except Exception as e:
            node_errors += 1
            logger.error(f'Node insert error [{nid}]: {type(e).__name__}: {e}')
logger.info(f'  Neo4j nodes ingested in {time.time()-t0:.1f}s (errors: {node_errors})')

# Neo4j: edges
logger.info(f'Ingesting {len(edges)} edges to Neo4j...')
edge_errors, edge_skipped = 0, 0
t0 = time.time()
with driver.session() as s:
    for src, tgt, rel, props in edges:
        if src not in nodes or tgt not in nodes:
            edge_skipped += 1
            continue
        try:
            pc = ''
            if props:
                sp = [f'r.`{k}` = "{v}"' for k, v in props.items() if v]
                if sp: pc = ' SET ' + ', '.join(sp)
            s.run(f'MATCH (a {{node_id: $s}}) MATCH (b {{node_id: $t}}) MERGE (a)-[r:{rel}]->(b){pc}', s=src, t=tgt)
        except Exception as e:
            edge_errors += 1
            logger.error(f'Edge insert error [{src}]-[{rel}]->[{tgt}]: {type(e).__name__}: {e}')
logger.info(f'  Neo4j edges ingested in {time.time()-t0:.1f}s (errors: {edge_errors}, skipped: {edge_skipped})')

# Weaviate: batched insert
logger.info('Ingesting to Weaviate (batched)...')
BATCH_SIZE = 50
def batch_insert(name, data):
    col = wv_client.collections.get(name)
    batch_errors = 0
    for start in range(0, len(data), BATCH_SIZE):
        try:
            col.data.insert_many([DataObject(properties=item) for item in data[start:start+BATCH_SIZE]])
        except Exception as e:
            batch_errors += 1
            logger.error(f'Weaviate batch error [{name}] at offset {start}: {type(e).__name__}: {e}')
    logger.info(f'  {name}: {len(data)} objects (batch errors: {batch_errors})')
if entity_vdb: batch_insert('EntityEmbedding', entity_vdb)
if relationship_vdb: batch_insert('RelationshipEmbedding', relationship_vdb)
if keywords_vdb: batch_insert('ContentKeyword', keywords_vdb)
if chunk_vdb: batch_insert('PaperChunk', chunk_vdb)

# Stats
with driver.session() as s:
    nc = s.run('MATCH (n) RETURN count(n) as c').single()['c']
    ec = s.run('MATCH ()-[r]->() RETURN count(r) as c').single()['c']
    lc = s.run('MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt ORDER BY cnt DESC').data()
    rc = s.run('MATCH ()-[r]->() RETURN type(r) as relType, count(r) as cnt ORDER BY cnt DESC').data()

sep = '=' * 60
logger.info(f'\n{sep}')
logger.info(f'KG CONSTRUCTION PIPELINE COMPLETE!')
logger.info(f'{sep}')
logger.info(f'Neo4j: {nc} nodes, {ec} edges')
logger.info(f'--- Node Distribution ---')
for row in lc: logger.info(f'  {row["label"]:20s}: {row["cnt"]}')
logger.info(f'--- Edge Distribution ---')
for row in rc: logger.info(f'  {row["relType"]:20s}: {row["cnt"]}')

wv_client.close(); driver.close()
end_cell('Cell 7: Database Ingestion', {
    'Neo4j nodes': nc, 'Neo4j edges': ec,
    'Node insert errors': node_errors, 'Edge insert errors': edge_errors,
    'Edge skipped (missing src/tgt)': edge_skipped
})
