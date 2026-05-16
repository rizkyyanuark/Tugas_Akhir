"""
ETL Worker Dispatch Tests
=========================
Dry-run checks for Airflow command names, worker registry, and import-time
contracts. These tests intentionally avoid external API calls and databases.

Run:
    cd backend/package
    python -m pytest knowledge/etl/tests/test_etl_dispatch.py -q
"""


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
    "lec_extract_siakadu",
    "lec_merge",
    "lec_enrich",
    "lec_transform",
    "lec_load",
]


def test_all_dag_commands_in_task_choices():
    from knowledge.etl.run_worker import TASK_CHOICES

    for cmd in PAPERS_DAG_COMMANDS + LECTURERS_DAG_COMMANDS:
        assert cmd in TASK_CHOICES, f"DAG command '{cmd}' missing from TASK_CHOICES"


def test_task_registry_handlers_are_callable():
    from knowledge.etl.run_worker import TASK_REGISTRY

    for cmd in PAPERS_DAG_COMMANDS + LECTURERS_DAG_COMMANDS:
        assert cmd in TASK_REGISTRY, f"No handler registered for '{cmd}'"
        assert callable(TASK_REGISTRY[cmd]), f"Handler for '{cmd}' is not callable"


def test_worker_package_exports_runtime_and_registry():
    from knowledge.etl.worker import RunConfig, TASK_CHOICES, TASK_REGISTRY, dispatch_task

    config = RunConfig(mode="sample", sample_size=3, prodi_filter="S1-TI")

    assert config.is_sample is True
    assert config.is_full is False
    assert "lec_extract_siakadu" in TASK_CHOICES
    assert "paper_transform" in TASK_REGISTRY
    assert callable(dispatch_task)


def test_papers_service_functions_importable():
    from knowledge.etl.services.unesa_papers import (
        run_scopus_processing,
        run_scopus_scraping,
        run_scholar_enrichment,
        run_scholar_scraping,
        run_supabase_insert,
    )

    assert callable(run_scopus_scraping)
    assert callable(run_scopus_processing)
    assert callable(run_scholar_scraping)
    assert callable(run_scholar_enrichment)
    assert callable(run_supabase_insert)


def test_lecturers_service_functions_importable():
    from knowledge.etl.services.unesa_lecturers import (
        fetch_pddikti_data,
        run_enrichment,
        run_post_processing,
        run_smart_merge,
        run_supabase_sync,
        scrape_university_websites,
    )

    assert callable(scrape_university_websites)
    assert callable(fetch_pddikti_data)
    assert callable(run_smart_merge)
    assert callable(run_enrichment)
    assert callable(run_post_processing)
    assert callable(run_supabase_sync)


def test_siakadu_identity_service_importable():
    from knowledge.etl.services.siakadu_identity import enrich_with_siakadu, fetch_siakadu_data

    assert callable(fetch_siakadu_data)
    assert callable(enrich_with_siakadu)


def test_etl_path_modules_importable():
    from knowledge.etl.services.lecturer_paths import FINAL_CSV, SCRAPE_SIAKADU_PATH
    from knowledge.etl.services.paper_paths import SCHOLAR_CSV, SCOPUS_CSV

    assert FINAL_CSV is not None
    assert SCRAPE_SIAKADU_PATH is not None
    assert SCOPUS_CSV is not None
    assert SCHOLAR_CSV is not None


def test_lecturer_downstream_tasks_do_not_skip_on_fresh_outputs(monkeypatch):
    import pandas as pd
    from knowledge.etl.pipelines import unesa_lecturers as pipeline
    import knowledge.etl.services.unesa_lecturers as lecturer_service

    class Config:
        is_sample = False
        sample_size = 50
        prodi_filter = None

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Freshness skip must only be used for extraction tasks")

    monkeypatch.setattr(pipeline, "_should_skip_extract", fail_if_called)
    monkeypatch.setattr(pipeline, "_load_or_extract_web", lambda config: pd.DataFrame([{"nama_norm": "a"}]))
    monkeypatch.setattr(pipeline, "_load_or_extract_pddikti", lambda config: pd.DataFrame([{"nama_norm": "a"}]))
    monkeypatch.setattr(lecturer_service, "run_smart_merge", lambda df_web, df_pddikti: "merged.csv")
    monkeypatch.setattr(lecturer_service, "run_enrichment", lambda scholar_sample=None: "final.csv")
    monkeypatch.setattr(lecturer_service, "run_post_processing", lambda: "final.csv")

    pipeline._lec_merge(Config())
    pipeline._lec_enrich(Config())
    pipeline._lec_transform(Config())


def test_scholar_verification_compatibility_client_importable():
    from knowledge.etl.clients.scholar_client import ScholarVerificationClient

    client = ScholarVerificationClient(proxy_url="")
    assert callable(client.verify_batch)


def test_storage_compatibility_helpers_importable(tmp_path):
    from knowledge.etl.utils.storage import (
        get_path_obj,
        normalize_storage_path,
        path_name,
        smart_exists,
        smart_unlink,
    )

    target = get_path_obj(tmp_path, "sample.csv")
    assert path_name(target) == "sample.csv"
    assert smart_exists(target) is False
    smart_unlink(target)
    assert get_path_obj("s3://bucket/prefix", "sample.csv") == "s3://bucket/prefix/sample.csv"
    assert normalize_storage_path("s3:/bucket/prefix/sample.csv") == "s3://bucket/prefix/sample.csv"
    assert path_name("s3://bucket/prefix/sample.csv") == "sample.csv"


def test_siakadu_parser_extracts_lecturer_identities_only():
    from knowledge.etl.clients.siakadu_client import SiakaduClient

    html = """
    <html><body>
      <section>
        <p>Nama : Wahyu Sasongko Putro</p>
        <p>JK : L</p>
        <p>NIP : 202504079</p>
        <p>NIDN : 9990475057</p>
      </section>
      <section>
        <p>Nama : Mahasiswa Contoh</p>
        <p>NIM : 24051234567</p>
      </section>
    </body></html>
    """

    records = SiakaduClient.parse_lecturers(
        html,
        prodi_code="20201",
        prodi_name="S1 Teknik Elektro",
        source_url="https://siakadu.unesa.ac.id/prodi/teknik-elektro",
    )

    assert len(records) == 1
    assert records[0]["nama_norm"] == "Wahyu Sasongko Putro"
    assert records[0]["nip"] == "202504079"
    assert records[0]["nidn"] == "9990475057"
    assert records[0]["source"] == "SIAKADU"


def test_siakadu_enrichment_fills_missing_identity(monkeypatch):
    import pandas as pd
    import knowledge.etl.services.siakadu_identity as service

    monkeypatch.setattr(
        service,
        "load_siakadu_cache_or_fetch",
        lambda: pd.DataFrame(
            [
                {
                    "nama_dosen": "Wahyu Sasongko Putro",
                    "nama_norm": "Wahyu Sasongko Putro",
                    "nip": "202504079",
                    "nidn": "9990475057",
                    "prodi_name": "S1 Teknik Elektro",
                    "source_url": "https://siakadu.unesa.ac.id/prodi/teknik-elektro",
                }
            ]
        ),
    )

    df = pd.DataFrame(
        [
            {
                "nama_dosen": "Ir. Wahyu Sasongko Putro, B.Eng., M.Sc.",
                "nama_norm": "Wahyu Sasongko Putro",
                "nip": None,
                "nidn": "9990475057",
                "prodi": "S1 Teknik Elektro",
                "source": "WEB+PDDIKTI",
            },
        ]
    )

    enriched = service.enrich_with_siakadu(df)

    assert enriched.loc[0, "nip"] == "202504079"
    assert enriched.loc[0, "nidn"] == "9990475057"
    assert enriched.loc[0, "source"] == "WEB+PDDIKTI+SIAKADU"
    assert enriched.loc[0, "identity_source"] == "SIAKADU"


def test_keyword_scraper_importable():
    import knowledge.etl.clients.keyword_scraper as keyword_scraper

    assert callable(keyword_scraper.enrich_single_paper)


def test_config_module_loads():
    from knowledge.etl.config import (
        PROCESSED_DATA_DIR,
        RAW_DATA_DIR,
        SAVE_DIR,
        SUPABASE_KEY,
        SUPABASE_URL,
    )

    assert RAW_DATA_DIR is not None
    assert PROCESSED_DATA_DIR is not None
    assert SAVE_DIR is not None
    assert SUPABASE_URL is not None
    assert SUPABASE_KEY is not None
