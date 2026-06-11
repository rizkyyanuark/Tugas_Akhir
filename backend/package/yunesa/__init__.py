from pathlib import Path

from dotenv import load_dotenv

# Prefer local backend `.env`, then fall back to repo-root `.env`.
load_dotenv(".env", override=True)
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
if _ROOT_ENV.exists():
    load_dotenv(_ROOT_ENV, override=False)

from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from importlib import import_module  # noqa: E402

from yunesa.config import config as config  # noqa: E402

__version__ = "0.6.0"

executor = ThreadPoolExecutor()  # noqa: E402


def get_version():
    """Return the YUNESA version."""
    return __version__


def __getattr__(name: str):
    if name in {"graph_base", "knowledge_base"}:
        knowledge = import_module("yunesa.knowledge")
        return getattr(knowledge, name)
    if name in {"agents", "knowledge", "services"}:
        module = import_module(f"yunesa.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'yunesa' has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | {"agents", "graph_base", "knowledge", "knowledge_base", "services"})
