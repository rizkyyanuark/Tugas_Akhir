import json
import glob
from pathlib import Path

notebooks = glob.glob(str(Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph") / "*.ipynb"))

for nb_path in notebooks:
    name = Path(nb_path).name
    try:
        with open(nb_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
        for cell_idx, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") == "code":
                source = "".join(cell.get("source", []))
                if "write_vector_index_to_milvus" in source or "write_milvus" in source:
                    print(f"[{name} cell {cell_idx}]")
                    print(source)
                    print("=" * 60)
    except Exception as e:
        print(f"Error on {name}: {e}")
