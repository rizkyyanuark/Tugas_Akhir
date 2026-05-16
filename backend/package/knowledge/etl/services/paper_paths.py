from __future__ import annotations

from ..config import SAVE_DIR
from ..utils.storage import get_path_obj


SCOPUS_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scopus.csv")
SCOPUS_RAW_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scopus_raw.csv")
SCHOLAR_RAW_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scholar_raw.csv")
SCHOLAR_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scholar.csv")
SCHOLAR_TEMP_CSV = get_path_obj(SAVE_DIR, "lecturer_papers_scholar_temp.csv")
