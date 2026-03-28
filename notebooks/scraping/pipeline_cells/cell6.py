# ══════════════════════════════════════════════════════════════════════
# CELL 6: Distillation & Entity Embeddings (Strwythura Part 5)
# ══════════════════════════════════════════════════════════════════════
import gensim
start_cell('Cell 6: Distillation & Embeddings')

high_centrality = {lk for lk, e in entity_store.items() if e['count'] >= 2}
low_centrality = {lk for lk, e in entity_store.items() if e['count'] < 2}
logger.info(f'Centrality filter: {len(high_centrality)} high (count>=2), {len(low_centrality)} low (count<2)')

w2v_sentences = []
for seq in entity_sequences:
    if len(seq) >= 2:
        w2v_sentences.append([str(uid) for uid in seq])

logger.info(f'Word2Vec training sentences: {len(w2v_sentences)}')

if w2v_sentences:
    w2v_model = gensim.models.Word2Vec(
        sentences=w2v_sentences,
        vector_size=32,
        window=max(len(s) for s in w2v_sentences),
        min_count=1,
        sg=1,
    )
    w2v_model.save('file_tabulars/entity_embeddings.w2v')
    logger.info(f'Entity embeddings trained: {len(w2v_model.wv)} vectors, dim={w2v_model.wv.vector_size}')
    uid_to_lk = {str(e['uid']): lk for lk, e in entity_store.items()}
    for test_uid in list(w2v_model.wv.index_to_key)[:3]:
        similar = w2v_model.wv.most_similar(test_uid, topn=3)
        test_name = entity_store.get(uid_to_lk.get(test_uid, ''), {}).get('text', '?')
        sim_names = [(entity_store.get(uid_to_lk.get(s[0], ''), {}).get('text', '?'), round(s[1], 3)) for s in similar]
        logger.info(f'  Similar to "{test_name}": {sim_names}')
else:
    logger.warning('Not enough entity sequences for Word2Vec training')

end_cell('Cell 6: Distillation & Embeddings', {
    'High centrality entities': len(high_centrality),
    'Low centrality (filtered)': len(low_centrality),
    'W2V sentences': len(w2v_sentences),
    'Total nodes': len(nodes), 'Total edges': len(edges)
})
