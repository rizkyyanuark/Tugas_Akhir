"""Re-export utility functions for backward compatibility with client modules.

All implementations live in etl/utils/utils.py.
This shim allows clients/ to keep using `from .utils import ...`.
"""
from ..utils.utils import (  # noqa: F401
    clean_name_expert,
    normalize_name,
    fuzzy_match_name,
    extract_ids_from_links,
    make_entry,
    clean_identifier,
    enforce_strict_types,
    save_final_csv,
)
