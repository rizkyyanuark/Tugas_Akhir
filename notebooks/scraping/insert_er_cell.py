"""
Script to insert Cell 4.5 (Entity Resolution) into kg_construction.ipynb
Run this once, then delete this script.
"""
import json

path = r'C:\Users\rizky_11yf1be\Desktop\Tugas_Akhir\notebooks\scraping\kg_construction.ipynb'

with open(path, 'r', encoding='utf-8') as f:
    nb = json.load(f)

# Find index of Cell 5 (Relationship Extraction)
cell5_idx = None
for i, cell in enumerate(nb['cells']):
    src = ''.join(cell['source'])
    if 'CELL 5: Relationship Extraction' in src:
        cell5_idx = i
        break

if cell5_idx is None:
    print("ERROR: Could not find Cell 5")
    exit(1)

# Entity Resolution cell source
er_source = r'''# ══════════════════════════════════════════════════════════════════════
# CELL 4.5: Entity Resolution (Deduplication & Unification)
# ══════════════════════════════════════════════════════════════════════
# PROBLEM: "QoS" vs "Quality of Service (QoS)" vs "QoS (Quality of
# Services)" are stored as separate nodes, but they should be ONE node.
# Same for bilingual: "PCA" vs "Principal Component Analysis" vs
# "Analisis Komponen Utama".
#
# SOLUTION: 3-Layer Entity Resolution
#   Layer 1: Regex — extract abbreviation ↔ full-name pairs
#   Layer 2: LLM  — cluster synonyms (handles bilingual + semantics)
#   Layer 3: Merge — unify entity_dedup so Cell 5 uses canonical IDs
# ──────────────────────────────────────────────────────────────────────

import re
from collections import defaultdict

# ── Layer 1: Abbreviation Extraction ──
# Detect patterns like "Quality of Service (QoS)" or "CNN (Convolutional Neural Network)"
abbrev_pattern = re.compile(r'([A-Za-z][\w\s\-]+?)\s*\(([A-Z][A-Za-z0-9\s\-\.]*)\)')
abbrev_pattern_rev = re.compile(r'([A-Z][A-Z0-9]{1,10})\s*\(([A-Za-z][\w\s\-]+?)\)')

alias_map = {}  # normalized_variant -> canonical_normalized_form

# Scan all extracted entities for abbreviation patterns
all_entity_texts = set()
for pid, ents in extracted_entities.items():
    for e in ents:
        all_entity_texts.add(e['text'].strip())

# Also scan the abstracts for parenthetical abbreviation patterns
for pid, text in processed_texts.items():
    # Pattern: "Full Name (ABBREV)"
    for match in abbrev_pattern.finditer(text):
        full_name = match.group(1).strip()
        abbrev = match.group(2).strip()
        if len(abbrev) >= 2 and len(full_name) > len(abbrev):
            canonical = normalize_text(full_name)
            alias_map[normalize_text(abbrev)] = canonical
            alias_map[canonical] = canonical

    # Pattern: "ABBREV (Full Name)"
    for match in abbrev_pattern_rev.finditer(text):
        abbrev = match.group(1).strip()
        full_name = match.group(2).strip()
        if len(abbrev) >= 2 and len(full_name) > len(abbrev):
            canonical = normalize_text(full_name)
            alias_map[normalize_text(abbrev)] = canonical
            alias_map[canonical] = canonical

print(f"Layer 1 (Regex): Found {len(alias_map)} abbreviation aliases")

# ── Layer 2: LLM Synonym Clustering ──
# Batch unique entity names and ask LLM to group synonyms
unique_entities = list(all_entity_texts)
CLUSTER_BATCH = 80  # entities per LLM call

CLUSTER_PROMPT = """Kamu adalah ahli Entity Resolution untuk Knowledge Graph akademik.

Diberikan daftar entitas yang diekstrak dari paper akademik (campuran Bahasa Indonesia & Inggris).
Tugasmu: kelompokkan entitas yang BERMAKNA SAMA menjadi satu grup.

Contoh:
- "QoS", "Quality of Service", "Quality of Service (QoS)" → sama
- "CNN", "Convolutional Neural Network" → sama
- "PCA", "Principal Component Analysis", "Analisis Komponen Utama" → sama
- "SVM", "Support Vector Machine" → sama
- "Jaringan Saraf Tiruan", "Neural Network", "ANN" → sama
- "akurasi", "accuracy" → sama
- "precision", "presisi" → sama

## Daftar Entitas:
{entity_list}

## Output JSON (strict format):
{{
  "groups": [
    {{
      "canonical": "nama kanonikal dalam Bahasa Inggris (pilih yang paling lengkap dan standar)",
      "members": ["variasi 1", "variasi 2", "variasi 3"]
    }}
  ]
}}

ATURAN:
- canonical HARUS dalam Bahasa Inggris dan merupakan nama paling standar/lengkap.
- Hanya kelompokkan yang BENAR-BENAR sinonim/singkatan dari konsep yang SAMA.
- Entitas yang unik (tidak punya sinonim) TIDAK perlu dimasukkan ke output.
- Jangan mengarang entitas baru, hanya gunakan yang ada di daftar.
"""

llm_clusters = 0
for start in range(0, len(unique_entities), CLUSTER_BATCH):
    batch = unique_entities[start:start + CLUSTER_BATCH]
    if len(batch) < 2:
        continue

    entity_list_str = "\n".join([f"- {e}" for e in batch])
    prompt = CLUSTER_PROMPT.format(entity_list=entity_list_str)

    result = call_openrouter(prompt)
    time.sleep(0.3)

    for group in result.get('groups', []):
        if not isinstance(group, dict):
            continue
        canonical = normalize_text(group.get('canonical', ''))
        members = group.get('members', [])
        if canonical and len(members) > 1:
            for member in members:
                norm_member = normalize_text(member)
                if norm_member and norm_member != canonical:
                    alias_map[norm_member] = canonical
            alias_map[canonical] = canonical
            llm_clusters += 1

print(f"Layer 2 (LLM): Found {llm_clusters} synonym clusters")
print(f"Total alias mappings: {len(alias_map)}")

# ── Layer 3: Rebuild entity_dedup with unified canonical forms ──
# This ensures Cell 5 will use canonical IDs when creating edges

old_dedup_count = len(set(
    normalize_text(e['text'])
    for ents in extracted_entities.values()
    for e in ents
))

# Apply alias resolution to all extracted entities
for pid in extracted_entities:
    for ent in extracted_entities[pid]:
        norm = normalize_text(ent['text'])
        if norm in alias_map:
            # Update the entity text to the canonical form
            canonical = alias_map[norm]
            ent['_canonical'] = canonical
        else:
            ent['_canonical'] = norm

# Count unique after resolution
resolved_norms = set()
for ents in extracted_entities.values():
    for e in ents:
        resolved_norms.add(e.get('_canonical', normalize_text(e['text'])))

new_count = len(resolved_norms)
merged = old_dedup_count - new_count

print(f"\nLayer 3 (Merge): {old_dedup_count} raw entities → {new_count} canonical entities")
print(f"  Merged {merged} duplicate entities")

# Show some example merges
sample_merges = defaultdict(list)
for norm, canonical in alias_map.items():
    if norm != canonical:
        sample_merges[canonical].append(norm)

print(f"\n📋 Sample entity merges (top 10):")
for canonical, aliases in list(sample_merges.items())[:10]:
    print(f"  ✅ {canonical} ← {aliases}")

print(f"\n✅ Cell 4.5 Complete: Entity Resolution applied")
'''

# Create the new cell
new_cell = {
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": er_source.split('\n')
}

# Fix: convert to list of lines with newlines
lines = er_source.split('\n')
new_cell['source'] = [line + '\n' for line in lines[:-1]]
if lines[-1]:
    new_cell['source'].append(lines[-1])

# Insert before Cell 5
nb['cells'].insert(cell5_idx, new_cell)

# Also update Cell 5 to use canonical forms from entity resolution
for i, cell in enumerate(nb['cells']):
    src = ''.join(cell['source'])
    if 'CELL 5: Relationship Extraction' in src:
        # Replace the normalize_text lookup in entity_dedup with canonical-aware version
        old_line = "        norm = normalize_text(txt)"
        new_line = "        norm = alias_map.get(normalize_text(txt), normalize_text(txt))"
        new_src = src.replace(old_line, new_line)

        # Also fix the relation source/target resolution
        old_rel = "        src_txt = normalize_text(rel.get('source', ''))"
        new_rel = "        src_txt = alias_map.get(normalize_text(rel.get('source', '')), normalize_text(rel.get('source', '')))"
        new_src = new_src.replace(old_rel, new_rel)

        old_tgt = "        tgt_txt = normalize_text(rel.get('target', ''))"
        new_tgt = "        tgt_txt = alias_map.get(normalize_text(rel.get('target', '')), normalize_text(rel.get('target', '')))"
        new_src = new_src.replace(old_tgt, new_tgt)

        lines2 = new_src.split('\n')
        cell['source'] = [line + '\n' for line in lines2[:-1]]
        if lines2[-1]:
            cell['source'].append(lines2[-1])
        break

with open(path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

print(f"SUCCESS: Inserted Entity Resolution cell at index {cell5_idx}")
print(f"Total cells now: {len(nb['cells'])}")
