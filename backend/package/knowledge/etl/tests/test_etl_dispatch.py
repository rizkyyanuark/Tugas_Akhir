"""
ETL Worker Dispatch Tests
==========================
Validates that ALL task names in both DAGs resolve to callable handlers.
This is a dry-run test — no API calls, no database, no Docker.

Run:
    cd backend/package
    python -m pytest knowledge/etl/tests/test_etl_dispatch.py -v
"""
import pytest


# ═══════════════════════════════════════════════════════════════════
#  Test 1: TASK_CHOICES matches what both DAGs send
# ═══════════════════════════════════════════════════════════════════

PAPERS_DAG_COMMANDS = [
    "paper_extract_scopus",
    "paper_extract_scholar",
    "paper_transform",
    "paper_load",
    "paper_notify",
]

LECTURERS_DAG_COMMANDS = [
    "lec_extract_web",
    "lec_extract_pddikti",
    "lec_merge",
    "lec_enrich",
    "lec_transform",
    "lec_load",
]


def test_all_papers_commands_in_task_choices():
    """Every papers DAG command must be in TASK_CHOICES."""
    from knowledge.etl.run_worker import TASK_CHOICES

    for cmd in PAPERS_DAG_COMMANDS:
        assert cmd in TASK_CHOICES, f"Papers DAG command '{cmd}' missing from TASK_CHOICES"


def test_all_lecturers_commands_in_task_choices():
    """Every lecturers DAG command must be in TASK_CHOICES."""
    from knowledge.etl.run_worker import TASK_CHOICES

    for cmd in LECTURERS_DAG_COMMANDS:
        assert cmd in TASK_CHOICES, f"Lecturers DAG command '{cmd}' missing from TASK_CHOICES"


# ═══════════════════════════════════════════════════════════════════
#  Test 2: Paper handlers exist and are callable
# ═══════════════════════════════════════════════════════════════════

def test_paper_handlers_are_callable():
    """Each paper_* command must map to a callable handler."""
    from knowledge.etl.run_worker import _PAPER_HANDLERS

    for cmd in PAPERS_DAG_COMMANDS:
        assert cmd in _PAPER_HANDLERS, f"No handler for '{cmd}'"
        assert callable(_PAPER_HANDLERS[cmd]), f"Handler for '{cmd}' is not callable"


# ═══════════════════════════════════════════════════════════════════
#  Test 3: Lecturers dispatch routing covers all lec_* commands
# ═══════════════════════════════════════════════════════════════════

def test_lec_dispatch_routes_all_commands():
    """_dispatch_task should not raise ValueError for any lec_* command."""
    from knowledge.etl.run_worker import _dispatch_task

    # We can't _execute_ the tasks (they need external services),
    # but we CAN verify the routing logic doesn't reject them.
    # The lec_dispatch function uses if/elif, so we just check
    # that it doesn't hit the "Unknown task" branch.
    for cmd in LECTURERS_DAG_COMMANDS:
        # This should NOT raise ValueError (ImportError is OK — it means
        # the routing resolved but the actual scraping module isn't available)
        try:
            _dispatch_task(cmd, test_mode=True)
        except ValueError:
            pytest.fail(f"_dispatch_task raised ValueError for '{cmd}' — routing is broken")
        except (ImportError, ModuleNotFoundError):
            pass  # Expected: scraping deps missing in test env
        except Exception:
            pass  # Any other error means the route was resolved


# ═══════════════════════════════════════════════════════════════════
#  Test 4: Service functions exist (import check)
# ═══════════════════════════════════════════════════════════════════

def test_papers_service_functions_importable():
    """All functions called from run_worker.py paper_* handlers must be importable."""
    pd = pytest.importorskip("pandas", reason="pandas not installed in local test env")
    from knowledge.etl.services.unesa_papers import (
        run_scopus_extraction,
        run_scholars_extraction,
        run_merge,
        run_enrichment,
        run_transform,
        run_database_commit,
    )
    
    assert callable(run_scopus_extraction)
    assert callable(run_scholars_extraction)
    assert callable(run_merge)
    assert callable(run_enrichment)
    assert callable(run_transform)
    assert callable(run_database_commit)


def test_scraping_pipeline_functions_importable():
    """All functions called from run_worker.py lec_* handlers must be importable."""
    try:
        from knowledge.etl.scraping.pipeline import (
            run_web_step,
            run_pddikti_step,
            run_smart_merge,
            run_enrichment,
            run_post_processing,
            run_supabase_sync,
        )
        
        assert callable(run_web_step)
        assert callable(run_pddikti_step)
        assert callable(run_smart_merge)
        assert callable(run_enrichment)
        assert callable(run_post_processing)
        assert callable(run_supabase_sync)
    except ImportError:
        pytest.skip("Scraping pipeline dependencies not installed in test env")


# ═══════════════════════════════════════════════════════════════════
#  Test 5: Config module loads without errors
# ═══════════════════════════════════════════════════════════════════

def test_config_module_loads():
    """Config module should import without crashing (env vars optional)."""
    from knowledge.etl.config import (
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        SUPABASE_URL,
        SUPABASE_KEY,
        GROQ_API_KEY,
    )
    assert RAW_DATA_DIR is not None
    assert PROCESSED_DATA_DIR is not None


# ═══════════════════════════════════════════════════════════════════
#  Test 6: No missing `import os` bug
# ═══════════════════════════════════════════════════════════════════

def test_unesa_papers_has_os_import():
    """Ensure `import os` is present in services/unesa_papers.py (needed by run_merge)."""
    pytest.importorskip("pandas", reason="pandas not installed in local test env")
    import knowledge.etl.services.unesa_papers as mod
    import os as _os
    
    # The module should have 'os' in its namespace  
    assert hasattr(mod, 'os'), "services/unesa_papers.py is missing `import os` — run_merge() will crash!"
    assert mod.os is _os
