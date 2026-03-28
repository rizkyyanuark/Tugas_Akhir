# ══════════════════════════════════════════════════════════════════════
# CELL 5: LLM Curation (Strwythura Part 4 — HITL replacement)
# ══════════════════════════════════════════════════════════════════════
start_cell('Cell 5: LLM Curation')

entity_vdb, relationship_vdb, keywords_vdb = [], [], []
entity_node_map = {}
VALID_LABELS = set(ONTOLOGY['node_types'].keys()) - {'Dosen','ExternalAuthor','Paper','ProgramStudi','Fakultas','Journal','Year','Keyword'}
logger.info(f'Valid entity labels for curation: {VALID_LABELS}')

CURATION_PROMPT = (
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
    '{{"entities": [{{"text": "exact text", "label": "Method", "description": "1 sentence"}}],\n'
    '  "relations": [{{"source": "entity1", "target": "entity2", "relation": "USES", "description": "1 sentence"}}]}}\n\n'
    "PENTING: Entitas harus text spans yang ADA di abstrak/judul. Minimal 3 entitas per abstrak."
)

total = len(extracted_entities)
llm_calls, llm_errors, skipped = 0, 0, 0
curated_ent_count, curated_rel_count = 0, 0

for i, (pid, lemma_keys) in enumerate(extracted_entities.items()):
    abstract = paper_abstracts.get(pid, '')
    title = paper_titles.get(pid, '')
    if len(abstract) < 50:
        skipped += 1
        logger.debug(f'SKIPPED paper {pid}: abstract too short ({len(abstract)} chars)')
        continue
    ent_hints = [{'text': entity_store[lk]['text'], 'label': entity_store[lk]['label']}
                 for lk in lemma_keys if lk in entity_store]
    enriched = call_openrouter(CURATION_PROMPT.format(
        title=title, abstract=abstract[:2000],
        entities=json.dumps(ent_hints, ensure_ascii=False)
    ))
    llm_calls += 1; time.sleep(0.3)
    if not enriched:
        llm_errors += 1
        logger.warning(f'LLM returned empty for paper: "{title[:60]}..."')
        continue
    for ent in enriched.get('entities', []):
        if not isinstance(ent, dict): continue
        txt = str(ent.get('text', '')).strip()
        lbl = str(ent.get('label', 'Field')).strip()
        desc = str(ent.get('description', '')).strip()
        lbl_cap = lbl.capitalize()
        if lbl_cap not in VALID_LABELS:
            lbl_cap = ONTOLOGY['ner_label_map'].get(lbl.lower(), 'Field')
        if not txt or len(txt) < 2: continue
        lk = resolve(make_lemma_key(txt))
        nid = f'{lbl_cap.lower()}_{md5(lk)}'
        if lk not in entity_node_map:
            entity_node_map[lk] = nid
            nodes[nid] = {'_label': lbl_cap, 'name': txt, 'description': desc}
            entity_vdb.append({'nodeId': nid, 'entityName': txt, 'entityType': lbl_cap, 'description': desc})
            curated_ent_count += 1
            logger.debug(f'CURATED entity [{lbl_cap}]: "{txt}" -> {nid}')
            if lk in entity_store:
                entity_store[lk]['description'] = desc
        edges.append((pid, entity_node_map[lk], f'HAS_{lbl_cap.upper()}', {}))
    for rel in enriched.get('relations', []):
        if not isinstance(rel, dict): continue
        slk = resolve(make_lemma_key(rel.get('source','')))
        tlk = resolve(make_lemma_key(rel.get('target','')))
        if slk in entity_node_map and tlk in entity_node_map:
            rtype = str(rel.get('relation','USES')).upper().replace(' ','_')
            rdesc = str(rel.get('description',''))
            edges.append((entity_node_map[slk], entity_node_map[tlk], rtype, {'description': rdesc}))
            relationship_vdb.append({'srcId': entity_node_map[slk], 'tgtId': entity_node_map[tlk], 'relType': rtype, 'description': rdesc})
            curated_rel_count += 1
            logger.debug(f'RELATION: {entity_node_map[slk]} -[{rtype}]-> {entity_node_map[tlk]}')
    kws = [entity_store[lk]['text'] for lk in lemma_keys if lk in entity_store]
    if kws: keywords_vdb.append({'keywords': '; '.join(kws), 'sourcePaper': pid})
    if (i+1) % 50 == 0:
        logger.info(f'  Curated {i+1}/{total} | entities: {curated_ent_count} | relations: {curated_rel_count} | errors: {llm_errors}')

end_cell('Cell 5: LLM Curation', {
    'Curated entities': curated_ent_count,
    'Curated relations': curated_rel_count,
    'LLM calls': llm_calls, 'LLM errors': llm_errors,
    'Skipped (short abstract)': skipped,
    'Total nodes now': len(nodes), 'Total edges now': len(edges)
})
