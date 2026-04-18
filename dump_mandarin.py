import os
import re
from collections import Counter

pattern = re.compile(r'([\u4e00-\u9fff]+)')

dirs_to_scan = [
    'backend/server/routers',
    'backend/package/yunesa/config',
    'backend/package/yunesa/services',
    'backend/package/yunesa/storage',
    'backend/package/yunesa/repositories',
    'backend/package/yunesa/plugins',
    'backend/package/yunesa/models',
    'backend/package/yunesa/utils',
    'backend/package/yunesa/knowledge',
    'backend/package/yunesa/agents',
]

base = 'c:/Users/rizky_11yf1be/Desktop/Tugas_Akhir'

phrases = Counter()

def extract_phrases(text):
    # Find continuous blocks of Chinese characters
    # Optionally could find sentence context, but let's grab the lines first.
    return pattern.findall(text)

with open(os.path.join(base, 'remaining_phrases.txt'), 'w', encoding='utf-8') as out_f:
    for d in dirs_to_scan:
        full_dir = os.path.join(base, d)
        if not os.path.exists(full_dir):
            continue
        for root, dirs, files in os.walk(full_dir):
            for f in sorted(files):
                if not (f.endswith('.py') or f.endswith('.md')):
                    continue
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, encoding='utf-8') as fh:
                        for idx, line in enumerate(fh):
                            if pattern.search(line):
                                out_f.write(f"{os.path.relpath(fpath, base)}:{idx+1}: {line.strip()}\n")
                except Exception:
                    pass
