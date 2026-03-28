# ══════════════════════════════════════════════════════════════════════
# CELL 4: Entity Resolution (Strwythura Part 1 + 4)
# ══════════════════════════════════════════════════════════════════════
start_cell('Cell 4: Entity Resolution (3-Layer)')

alias_map = {}

# ── Layer 2: Abbreviation Extraction from abstracts ──
abbr_pat1 = re.compile(r'([A-Za-z][\w\s\-]+?)\s*\(([A-Z][A-Za-z0-9\s\-\.]*?)\)')
abbr_pat2 = re.compile(r'([A-Z][A-Z0-9]{1,10})\s*\(([A-Za-z][\w\s\-]+?)\)')

abbr_found = 0
for pid, abstract in paper_abstracts.items():
    full = f'{paper_titles.get(pid, "")}. {abstract}'
    for pat in [abbr_pat1, abbr_pat2]:
        for m in pat.finditer(full):
            a, b = m.group(1).strip(), m.group(2).strip()
            short, long_ = (a, b) if len(a) < len(b) else (b, a)
            if len(short) >= 2:
                lk_short = make_lemma_key(short)
                lk_long = make_lemma_key(long_)
                if lk_short and lk_long and lk_short != lk_long:
                    alias_map[lk_short] = lk_long
                    abbr_found += 1
                    logger.debug(f'ABBREV alias: "{short}" -> "{long_}"')

logger.info(f'Layer 2 (Regex): {len(alias_map)} abbreviation aliases from {abbr_found} matches')

# ── Layer 3: LLM Synonym Clustering ──
unique_texts = [e['text'] for e in entity_store.values()]
BATCH = 80
CLUSTER_PROMPT = (
    "Kamu ahli Entity Resolution untuk KG akademik.\n"
    "Kelompokkan entitas yang BERMAKNA SAMA (sinonim, singkatan, terjemahan).\n\n"
    'Contoh: "QoS" = "Quality of Service" | "CNN" = "Convolutional Neural Network" | "akurasi" = "accuracy"\n\n'
    "Daftar entitas:\n{ents}\n\n"
    'Output JSON: {{"groups": [{{"canonical": "English standard name", "members": ["var1", "var2"]}}]}}\n'
    "Hanya kelompokkan yang BENAR-BENAR sinonim. Entitas unik tidak perlu dimasukkan."
)

llm_clusters = 0
llm_batch_count = 0
for start in range(0, len(unique_texts), BATCH):
    batch = unique_texts[start:start + BATCH]
    if len(batch) < 2: continue
    llm_batch_count += 1
    ents_str = '\n'.join([f'- {e}' for e in batch])
    result = call_openrouter(CLUSTER_PROMPT.format(ents=ents_str))
    time.sleep(0.3)
    for grp in result.get('groups', []):
        if not isinstance(grp, dict): continue
        canonical = grp.get('canonical', '')
        members = grp.get('members', [])
        if canonical and len(members) > 1:
            lk_canon = make_lemma_key(canonical)
            for member in members:
                lk_mem = make_lemma_key(member)
                if lk_mem and lk_mem != lk_canon:
                    alias_map[lk_mem] = lk_canon
                    logger.debug(f'LLM synonym: "{member}" -> "{canonical}"')
            llm_clusters += 1
    if llm_batch_count % 5 == 0:
        logger.info(f'  LLM clustering batch {llm_batch_count}/{(len(unique_texts)//BATCH)+1}...')

logger.info(f'Layer 3 (LLM): {llm_clusters} synonym clusters from {llm_batch_count} batches')

# ── Apply alias resolution ──
def resolve(lk):
    visited = set()
    while lk in alias_map and lk not in visited:
        visited.add(lk)
        lk = alias_map[lk]
    return lk

merged_count = 0
for pid in extracted_entities:
    resolved = []
    for lk in extracted_entities[pid]:
        canon = resolve(lk)
        if canon != lk:
            merged_count += 1
            logger.debug(f'MERGED: "{lk}" -> "{canon}" in paper {pid}')
        resolved.append(canon)
    extracted_entities[pid] = list(set(resolved))

end_cell('Cell 4: Entity Resolution (3-Layer)', {
    'Total alias mappings': len(alias_map),
    'Entity references merged': merged_count,
    'Abbreviation aliases (Layer 2)': abbr_found,
    'LLM synonym clusters (Layer 3)': llm_clusters
})
