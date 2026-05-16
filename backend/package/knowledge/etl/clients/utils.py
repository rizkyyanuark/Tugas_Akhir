"""
Re-export utility functions for client modules.
All core implementations live in etl/utils/utils.py.
"""
from ..utils.utils import (  # noqa: F401
    clean_lecturer_name,
    normalize_name,
    fuzzy_match_name,
    extract_ids_from_links,
    make_lecturer_entry,
    clean_identifier,
    enforce_strict_ids,
    save_final_csv,
)

# Aliases for backward compatibility during refactor
clean_name_expert = clean_lecturer_name
make_entry = make_lecturer_entry
enforce_strict_types = enforce_strict_ids
