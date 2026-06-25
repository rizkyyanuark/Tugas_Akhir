import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

nb_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph\construction-kg.ipynb")

try:
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    for cell_idx, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") == "code":
            source = "".join(cell.get("source", []))
            if "milvus" in source.lower() or "pymilvus" in source.lower():
                print(f"[construction-kg.ipynb cell {cell_idx}]")
                print(source)
                print("=" * 60)
except Exception as e:
    print("Error:", e)
