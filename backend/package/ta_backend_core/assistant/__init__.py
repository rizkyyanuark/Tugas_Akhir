from dotenv import load_dotenv

load_dotenv(".env", override=True)

from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from importlib import import_module  # noqa: E402

from ta_backend_core.assistant.config import config as config  # noqa: E402

__version__ = "0.6.0"

executor = ThreadPoolExecutor()  # noqa: E402


def get_version():
    """Return the Yuxi version."""
    return __version__


def __getattr__(name: str):
    if name in {"graph_base", "knowledge_base"}:
        knowledge = import_module("ta_backend_core.assistant.knowledge")
        return getattr(knowledge, name)
    raise AttributeError(f"module 'ta_backend_core' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | {"graph_base", "knowledge_base"})
