# ══════════════════════════════════════════════════════════════════════
# CELL 3: Text Parsing + NER (Strwythura Part 3)
# ══════════════════════════════════════════════════════════════════════
start_cell('Cell 3: Text Parsing + NER')

GLINER_SET1 = ['method', 'algorithm', 'evaluation metric', 'software', 'model']
GLINER_SET2 = ['dataset', 'problem', 'task', 'tool', 'technology', 'framework', 'field']
GLINER_THRESHOLD = 0.15

entity_store = OrderedDict()
entity_sequences = []
entity_uid = 0

SRC_NER = 0    # GLiNER NER (highest priority)
SRC_TITLE = 1  # Title regex
SRC_CSV = 2    # CSV keywords

extracted_entities = {}
chunk_vdb = []
_ner_count, _title_count, _csv_count = 0, 0, 0

def make_lemma_key(text):
    # Strwythura-style POS.lemma key (from nlp.py tokenize_lemma)
    doc = nlp(str(text).strip())
    parts = []
    for tok in doc:
        pos = 'NOUN' if tok.pos_ in ('PROPN', 'NOUN') else tok.pos_
        if pos in ('NOUN', 'ADJ', 'VERB'):
            parts.append(f'{pos}.{tok.lemma_.lower()}')
    return ' '.join(parts) if parts else normalize_text(text)

def register_entity(text, label, source_priority):
    # Register entity in store with Strwythura-style dedup by lemma_key.
    global entity_uid, _ner_count, _title_count, _csv_count
    lemma_key = make_lemma_key(text)
    if not lemma_key or len(lemma_key) < 3:
        return None
    mapped_label = ONTOLOGY['ner_label_map'].get(label.lower(), 'Field')
    if lemma_key not in entity_store:
        entity_store[lemma_key] = {
            'uid': entity_uid, 'text': text.strip(), 'label': mapped_label,
            'count': 1, 'source': source_priority, 'description': ''
        }
        entity_uid += 1
        logger.debug(f'NEW entity [{mapped_label}]: "{text.strip()}" -> lemma_key="{lemma_key}" (src={source_priority})')
        if source_priority == SRC_NER: _ner_count += 1
        elif source_priority == SRC_TITLE: _title_count += 1
        else: _csv_count += 1
    elif source_priority < entity_store[lemma_key]['source']:
        old_src = entity_store[lemma_key]['source']
        entity_store[lemma_key]['text'] = text.strip()
        entity_store[lemma_key]['label'] = mapped_label
        entity_store[lemma_key]['source'] = source_priority
        entity_store[lemma_key]['count'] += 1
        logger.debug(f'PROMOTED entity: "{text.strip()}" source {old_src} -> {source_priority}')
    else:
        entity_store[lemma_key]['count'] += 1
    return lemma_key

total = len(paper_abstracts)
gliner_errors = 0
for i, (pid, abstract) in enumerate(paper_abstracts.items()):
    title = paper_titles.get(pid, '')
    full_text = f'{title}. {abstract}'
    paper_node = nodes.get(pid, {})
    chunk_vdb.append({'title': title, 'content': full_text, 'year': paper_node.get('year',''), 'paperUrl': paper_node.get('url','')})
    paper_lemma_keys = []
    # Pass 1: GLiNER NER
    input_text = full_text[:2000]
    for label_set in [GLINER_SET1, GLINER_SET2]:
        try:
            ents = gliner_model.predict_entities(input_text, label_set, threshold=GLINER_THRESHOLD)
            for e in ents:
                lk = register_entity(e['text'], e['label'], SRC_NER)
                if lk: paper_lemma_keys.append(lk)
        except Exception as ex:
            gliner_errors += 1
            logger.debug(f'GLiNER error on paper {pid}: {type(ex).__name__}: {ex}')
    # Pass 2: Title regex (abbreviations + multi-word)
    for term in re.findall(r'[A-Z]{2,}[0-9]*', title):
        lk = register_entity(term, 'method', SRC_TITLE)
        if lk: paper_lemma_keys.append(lk)
    for term in re.findall(r'[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)+', title):
        lk = register_entity(term, 'method', SRC_TITLE)
        if lk: paper_lemma_keys.append(lk)
    # Pass 3: CSV Keywords
    paper_row = df_sample[df_sample['Title'].str.strip() == title]
    if not paper_row.empty:
        kw_raw = str(paper_row.iloc[0].get('Keywords', ''))
        if kw_raw and kw_raw != 'nan':
            for kw in re.split(r'[;,]', kw_raw):
                kw = kw.strip()
                if kw and len(kw) > 2:
                    lk = register_entity(kw, 'field', SRC_CSV)
                    if lk: paper_lemma_keys.append(lk)
    extracted_entities[pid] = list(set(paper_lemma_keys))
    entity_sequences.append([entity_store[lk]['uid'] for lk in paper_lemma_keys if lk in entity_store])
    if (i + 1) % 50 == 0:
        logger.info(f'  Parsed {i+1}/{total} papers | unique entities so far: {len(entity_store)}')

label_dist = defaultdict(int)
for e in entity_store.values(): label_dist[e['label']] += 1

end_cell('Cell 3: Text Parsing + NER', {
    'Unique entities (lemma-key deduped)': len(entity_store),
    'From NER': _ner_count, 'From Title Regex': _title_count, 'From CSV': _csv_count,
    'GLiNER errors': gliner_errors,
    'Label distribution': dict(label_dist)
})
