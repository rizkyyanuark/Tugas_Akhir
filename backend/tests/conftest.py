import sys
import os
from pathlib import Path

# Menambahkan root project `Tugas_Akhir` ke PYTHONPATH saat Pytest dijalankan
# agar impor seperti `src.utils...` tidak putus.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
