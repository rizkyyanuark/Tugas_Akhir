# ══════════════════════════════════════════════════════════════════════
# CELL 2: Backbone from Structured Data (Strwythura Part 1)
# ══════════════════════════════════════════════════════════════════════
start_cell('Cell 2: Backbone Construction')

df_papers = pd.read_csv('file_tabulars/dosen_papers_scholar_colab.csv').fillna('')
df_dosen = pd.read_csv('file_tabulars/dosen_infokom_final.csv').fillna('')
logger.info(f'CSV loaded: {len(df_papers)} papers, {len(df_dosen)} dosen')

MAX_PAPERS = 500
df_with_abstract = df_papers[df_papers['Abstract'].str.len() > 50]
df_sample = df_with_abstract.sample(n=min(MAX_PAPERS, len(df_with_abstract)), random_state=42).copy()
logger.info(f'Filtered: {len(df_with_abstract)} with abstracts, sampled {len(df_sample)}')

dosen_lookup = {
    str(r['scholar_id']).strip(): r.to_dict()
    for _, r in df_dosen.iterrows()
    if str(r['scholar_id']).strip() and str(r['scholar_id']).strip().lower() != 'nan'
}

nodes, edges = {}, []
paper_abstracts, paper_titles = {}, {}

# Dosen -> ProgramStudi -> Fakultas
dosen_count = 0
for _, row in df_dosen.iterrows():
    name = row.get('nama_norm', '') or row.get('nama_dosen', '')
    if not name: continue
    dosen_count += 1
    sid = str(row.get('scholar_id', '')).strip()
    d_id = f'dosen_{sid}' if sid and sid.lower() != 'nan' else f'dosen_{md5(name)}'
    prodi = str(row.get('prodi', '')).strip() or 'Unknown'
    nodes[d_id] = {'_label': 'Dosen', 'name': name, 'prodi': prodi,
                   'scholar_id': sid, 'nip': str(row.get('nip', '')), 'nidn': str(row.get('nidn', ''))}
    p_id = f'prodi_{normalize_text(prodi).replace(" ", "_")}'
    if p_id not in nodes: nodes[p_id] = {'_label': 'ProgramStudi', 'name': prodi}
    edges.append((d_id, p_id, 'MEMBER_OF', {}))
    fak = PRODI_FAKULTAS.get(prodi, 'Unknown')
    f_id = f'fak_{normalize_text(fak).replace(" ", "_")}'
    if f_id not in nodes: nodes[f_id] = {'_label': 'Fakultas', 'name': fak}
    edges.append((p_id, f_id, 'PART_OF', {}))

logger.info(f'Dosen backbone: {dosen_count} dosen registered')

# Papers -> Year, Journal, Authors, Keywords
paper_count, ext_author_count, keyword_count = 0, 0, 0
for _, row in df_sample.iterrows():
    t = str(row['Title']).strip()
    a = str(row['Abstract']).strip()
    y = str(row.get('Year', ''))[:4]
    journal = str(row.get('Journal', '')).strip()
    link = str(row.get('Link', '')); doi = str(row.get('DOI', '')).strip()
    if ('scholar' in link.lower() or not link or link == 'nan') and doi and doi != 'nan':
        link = f'https://doi.org/{doi}'
    pid = f'paper_{md5(t)}'
    nodes[pid] = {'_label': 'Paper', 'title': t, 'year': y, 'url': link, 'journal': journal}
    paper_abstracts[pid] = a; paper_titles[pid] = t
    paper_count += 1
    if y and y != 'nan':
        yid = f'year_{y}'
        if yid not in nodes: nodes[yid] = {'_label': 'Year', 'value': y}
        edges.append((pid, yid, 'PUBLISHED_YEAR', {}))
    j_clean = journal.split(',')[0].strip() if journal and journal != 'nan' else ''
    if j_clean:
        jid = f'journal_{md5(j_clean)}'
        if jid not in nodes: nodes[jid] = {'_label': 'Journal', 'name': j_clean}
        edges.append((pid, jid, 'PUBLISHED_IN', {}))
    authors = [x.strip() for x in str(row['Authors']).split(',') if x.strip()]
    aids = [x.strip() for x in str(row.get('Author IDs', '')).split(';') if x.strip()]
    for i, aname in enumerate(authors):
        asid = aids[i] if i < len(aids) else ''
        did = f'dosen_{asid}' if asid and asid in dosen_lookup else f'ext_{md5(aname)}'
        if did not in nodes:
            nodes[did] = {'_label': 'Dosen' if 'dosen_' in did else 'ExternalAuthor', 'name': aname}
            if 'ext_' in did: ext_author_count += 1
        edges.append((did, pid, 'WRITES', {'position': 'first' if i == 0 else 'co'}))
    kw_raw = str(row.get('Keywords', ''))
    if kw_raw and kw_raw != 'nan':
        for kw in re.split(r'[;,]', kw_raw):
            kw = kw.strip()
            if kw and len(kw) > 2:
                kwid = f'keyword_{md5(kw)}'
                if kwid not in nodes:
                    nodes[kwid] = {'_label': 'Keyword', 'name': kw}
                    keyword_count += 1
                edges.append((pid, kwid, 'HAS_KEYWORD', {}))

end_cell('Cell 2: Backbone Construction', {
    'Papers': paper_count, 'Dosen': dosen_count,
    'External Authors': ext_author_count, 'Keywords': keyword_count,
    'Total nodes': len(nodes), 'Total edges': len(edges)
})
