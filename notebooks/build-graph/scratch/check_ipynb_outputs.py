import json
import glob
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

notebooks = glob.glob(str(Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph") / "*.ipynb"))

for nb_path in notebooks:
    name = Path(nb_path).name
    try:
        with open(nb_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
        for cell_idx, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") == "code":
                outputs = cell.get("outputs", [])
                for out in outputs:
                    text = out.get("text", [])
                    if isinstance(text, list):
                        text = "".join(text)
                    if "milvus" in text.lower() or "neo4j" in text.lower() or "inserted" in text.lower():
                        print(f"[{name} cell {cell_idx}]")
                        lines = text.split("\n")
                        print("\n".join(lines[:10]))
                        print("=" * 40)
    except Exception as e:
        print(f"Error on {name}: {e}")
