"""YUNESA Academic Knowledge Graph – backward compatibility shim.

The canonical source of truth has been moved to
``backend/package/knowledge/etl/kg/yunesa_academic_kg.py``.

This ``__init__.py`` re-exports all public symbols from the production
package so that any legacy code still importing from ``src/`` will
continue to work without modification.
"""

import sys
from pathlib import Path

# Ensure backend package is on sys.path for seamless re-export
_BACKEND_PKG = Path(__file__).resolve().parents[3] / "backend" / "package"
if str(_BACKEND_PKG) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PKG))

from yunesa.knowledge import *  # noqa: F401,F403
from yunesa.knowledge import __all__  # noqa: F401
