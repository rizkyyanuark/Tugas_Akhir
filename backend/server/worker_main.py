"""ARQ worker entrypoint."""

import asyncio
import os
import sys

# Must be at the top level!
if sys.platform == "win32":
    # Add the grandparent directory of current file (the root directory) to sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from yunesa.services.run_worker import WorkerSettings

__all__ = ["WorkerSettings"]
