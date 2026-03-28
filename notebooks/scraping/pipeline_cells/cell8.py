# ══════════════════════════════════════════════════════════════════════
# CELL 8: Verification Queries
# ══════════════════════════════════════════════════════════════════════
start_cell('Cell 8: Verification Queries')

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

queries = [
    ('1. Metode Terpopuler', 'MATCH (p:Paper)-[:HAS_METHOD]->(m:Method) RETURN m.name AS Metode, COUNT(p) AS Jumlah ORDER BY Jumlah DESC LIMIT 10'),
    ('2. Paper Mirip (Metode Sama)', 'MATCH (p1:Paper)-[:HAS_METHOD]->(m:Method)<-[:HAS_METHOD]-(p2:Paper) WHERE p1 <> p2 RETURN p1.title AS Paper1, m.name AS Metode, p2.title AS Paper2 LIMIT 10'),
    ('3. Topik per Prodi', 'MATCH (ps:ProgramStudi)<-[:MEMBER_OF]-(d:Dosen)-[:WRITES]->(p:Paper)-[:IN_FIELD]->(f:Field) RETURN ps.name AS Prodi, f.name AS Field, COUNT(p) AS Total ORDER BY Total DESC LIMIT 10'),
    ('4. Kolaborasi Lintas Prodi', 'MATCH (d1:Dosen)-[:WRITES]->(p:Paper)<-[:WRITES]-(d2:Dosen) MATCH (d1)-[:MEMBER_OF]->(ps1) MATCH (d2)-[:MEMBER_OF]->(ps2) WHERE elementId(d1)<elementId(d2) AND ps1<>ps2 RETURN d1.name AS D1, ps1.name AS P1, d2.name AS D2, ps2.name AS P2, COUNT(p) AS Papers ORDER BY Papers DESC LIMIT 5'),
    ('5. Tren Model per Tahun', 'MATCH (p:Paper)-[:HAS_MODEL]->(m:Model) MATCH (p)-[:PUBLISHED_YEAR]->(y:Year) RETURN y.value AS Tahun, m.name AS Model, COUNT(p) AS Jumlah ORDER BY Tahun DESC, Jumlah DESC LIMIT 10'),
    ('6. Dosen Produktif & Spesialisasi', 'MATCH (d:Dosen)-[:WRITES]->(p:Paper)-[:IN_FIELD]->(f:Field) RETURN d.name AS Dosen, f.name AS Topik, COUNT(p) AS Total ORDER BY Total DESC LIMIT 10'),
    ('7. Problem vs Tool', 'MATCH (t:Tool)<-[:HAS_TOOL]-(p:Paper)-[:ADDRESSES]->(pr:Problem) RETURN pr.name AS Masalah, t.name AS Tool, COUNT(p) AS Kasus ORDER BY Kasus DESC LIMIT 10'),
    ('8. Metrik per Field', 'MATCH (f:Field)<-[:IN_FIELD]-(p:Paper)-[:HAS_METRIC]->(m:Metric) RETURN f.name AS Field, m.name AS Metrik, COUNT(p) AS Freq ORDER BY Freq DESC LIMIT 10'),
    ('9. Paper Kompleks', 'MATCH (p:Paper)-[:HAS_METHOD|HAS_MODEL]->(e) WITH p, COUNT(e) AS K, COLLECT(e.name) AS List WHERE K>1 RETURN p.title AS Paper, K, List ORDER BY K DESC LIMIT 5'),
    ('10. Pencarian Pakar Sebidang', 'MATCH (d1:Dosen)-[:WRITES]->(p1:Paper)-[:ADDRESSES]->(pr:Problem)<-[:ADDRESSES]-(p2:Paper)<-[:WRITES]-(d2:Dosen) WHERE d1<>d2 AND elementId(d1)<elementId(d2) RETURN pr.name AS Problem, d1.name AS Peneliti1, d2.name AS Peneliti2 LIMIT 10'),
]

passed, failed = 0, 0
for title, q in queries:
    logger.info(f'\n--- {title} ---')
    logger.debug(f'Query: {q}')
    with driver.session() as s:
        try:
            result = s.run(q).data()
            if result:
                passed += 1
                logger.info(f'  ✅ {len(result)} rows returned')
                display(pd.DataFrame(result))
            else:
                failed += 1
                logger.warning(f'  ⚠️ No results')
        except Exception as e:
            failed += 1
            logger.error(f'  ❌ Query error: {type(e).__name__}: {e}')

driver.close()

end_cell('Cell 8: Verification Queries', {
    'Queries passed': passed, 'Queries with no results': failed,
    'Log file': LOG_FILE
})

logger.info(f'Full debug log saved to: {LOG_FILE}')
