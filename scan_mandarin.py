import os
import re

pattern = re.compile(r'[\u4e00-\u9fff]')

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

total_files = 0
total_lines = 0

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
                    lines_with_cn = sum(1 for line in fh if pattern.search(line))
                if lines_with_cn > 0:
                    rel = os.path.relpath(fpath, base)
                    print(f"{rel}: {lines_with_cn} lines")
                    total_files += 1
                    total_lines += lines_with_cn
            except Exception:
                pass

print(f"\nTotal: {total_files} files, {total_lines} lines with Mandarin")
