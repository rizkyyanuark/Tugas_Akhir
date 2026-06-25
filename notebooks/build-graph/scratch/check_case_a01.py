import json
from pathlib import Path

path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\notebooks\build-graph\eval_pipeline\data\eval_cases_ranked_56.json")
cases = json.loads(path.read_text(encoding="utf-8"))

for case in cases:
    if case["id"] == "A01":
        print(json.dumps(case, indent=2))
