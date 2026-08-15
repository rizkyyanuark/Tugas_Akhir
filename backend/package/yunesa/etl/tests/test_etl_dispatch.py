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
    "paper_enrich",
    "paper_load",
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

KG_DAG_COMMANDS = [
    "kg_load_data",
    "kg_extract_entities",
    "kg_build_graph",
    "kg_write_stores",
]


def test_all_dag_commands_in_task_choices():
    from yunesa.etl.run_worker import TASK_CHOICES

    for cmd in PAPERS_DAG_COMMANDS + LECTURERS_DAG_COMMANDS + KG_DAG_COMMANDS:
        assert cmd in TASK_CHOICES, f"DAG command '{cmd}' missing from TASK_CHOICES"


def test_task_registry_handlers_are_callable():
    from yunesa.etl.run_worker import TASK_REGISTRY

    for cmd in PAPERS_DAG_COMMANDS + LECTURERS_DAG_COMMANDS + KG_DAG_COMMANDS:
        assert cmd in TASK_REGISTRY, f"No handler registered for '{cmd}'"
        assert callable(TASK_REGISTRY[cmd]), f"Handler for '{cmd}' is not callable"


def test_worker_package_exports_runtime_and_registry():
    from yunesa.etl.worker import RunConfig, TASK_CHOICES, TASK_REGISTRY, dispatch_task

    config = RunConfig(mode="sample", sample_size=3, prodi_filter="S1-TI")

    assert config.is_sample is True
    assert config.is_full is False
    assert "lec_extract_siakadu" in TASK_CHOICES
    assert "paper_transform" in TASK_REGISTRY
    assert callable(dispatch_task)


def test_papers_service_functions_importable():
    from yunesa.etl.services.unesa_papers import (
        run_paper_enrichment,
        run_paper_transform,
        run_scopus_processing,
        run_scopus_scraping,
        run_scholar_enrichment,
        run_scholar_scraping,
        run_supabase_insert,
    )

    assert callable(run_paper_transform)
    assert callable(run_paper_enrichment)
    assert callable(run_scopus_scraping)
    assert callable(run_scopus_processing)
    assert callable(run_scholar_scraping)
    assert callable(run_scholar_enrichment)
    assert callable(run_supabase_insert)


def test_kg_service_functions_importable():
    from yunesa.etl.services.kg_service import (
        run_kg_build,
        run_kg_data_load,
        run_kg_entity_extraction,
        run_kg_write_stores,
    )

    assert callable(run_kg_data_load)
    assert callable(run_kg_entity_extraction)
    assert callable(run_kg_build)
    assert callable(run_kg_write_stores)

def test_scholar_scraping_requires_brightdata_proxy(monkeypatch):
    import yunesa.etl.services.unesa_papers as service

    monkeypatch.setattr(service, "PROXY_URL", "")
    monkeypatch.setattr(
        service,
        "_load_lecturers_from_supabase",
        lambda: (_ for _ in ()).throw(AssertionError("proxy config must fail first")),
    )

    assert service.run_scholar_scraping(proxy_url="") is None


def test_document_type_normalization_for_enrichment():
    from yunesa.etl.transform.enricher import normalize_document_type

    assert normalize_document_type("") == "article"
    assert normalize_document_type("Artikel") == "article"
    assert normalize_document_type("Article") == "article"
    assert normalize_document_type("Articles") == "article"
    assert normalize_document_type("journal-article") == "article"
    assert normalize_document_type("journal articles") == "article"
    assert normalize_document_type("JournalArticle") == "article"
    assert normalize_document_type("conference") == "conference paper"
    assert normalize_document_type("conference-paper") == "conference paper"
    assert normalize_document_type("proceedings-article") == "conference paper"
    assert normalize_document_type("Book Chapter") == "book chapter"


def test_venue_name_normalization_for_enrichment():
    from yunesa.etl.transform.enricher import normalize_venue_name

    assert (
        normalize_venue_name("Journal of Informatics and Computer Science (JINACS) 3 (04), 394-402, 2022")
        == "Journal of Informatics and Computer Science (JINACS)"
    )
    assert (
        normalize_venue_name("International Journal of Intelligent Engineering and Systems 13 (4), 156-170, 2020")
        == "International Journal of Intelligent Engineering and Systems"
    )
    assert (
        normalize_venue_name("Proceeding - 2020 3rd International Conference on Vocational Education and Electrical Engineering")
        == "Proceeding - 2020 3rd International Conference on Vocational Education and Electrical Engineering"
    )


def test_keyword_cleaner_rejects_tag_cloud_artifact():
    from yunesa.etl.transform.cleaner import clean_keyword_text

    artifact = '= [{"text":"bahan bakar", "size":1}, {"text":"facebook", "size":1}]'

    assert clean_keyword_text(artifact) == ""
    assert clean_keyword_text("Machine Learning; Education | Support Vector Machine") == (
        "machine learning,education,support vector machine"
    )


def test_supabase_loader_normalizes_document_type_before_upsert():
    import pandas as pd
    from yunesa.etl.load.supabase_loader import SupabaseLoader

    captured = {}

    class FakeTable:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self

        def execute(self):
            return None

    class FakeClient:
        def table(self, name):
            captured["table"] = name
            return FakeTable()

    loader = object.__new__(SupabaseLoader)
    loader.client = FakeClient()
    loader.key_role = "service_role"

    count = loader.upsert_papers(
        pd.DataFrame(
            [{
                "Title": "Document Type Normalization Paper",
                "Year": "2026",
                "Journal": "Journal of Informatics and Computer Science (JINACS) 3 (04), 394-402, 2022",
                "Document Type": "articles",
            }]
        )
    )

    assert count == 1
    assert captured["table"] == "papers"
    assert captured["on_conflict"] == "paper_id"
    assert captured["rows"][0]["document_type"] == "article"
    assert captured["rows"][0]["journal"] == "Journal of Informatics and Computer Science (JINACS)"


def test_generate_paper_id_ignores_placeholder_dois():
    from yunesa.etl.utils.hasher import generate_paper_id

    # Valid DOI
    id1 = generate_paper_id("10.1234/something", "A Great Paper", 2026)

    # Placeholder DOI - should ignore it and use title+year
    id2 = generate_paper_id("10.26740/jte.v9n1.p%p", "A Great Paper", 2026)

    # Paper with no DOI - should use title+year
    id3 = generate_paper_id(None, "A Great Paper", 2026)

    # id2 and id3 must be identical because they both fall back to title+year
    assert id2 == id3
    # id1 must be different because it uses the valid DOI
    assert id1 != id2


def test_supabase_loader_deduplicates_by_paper_id():
    import pandas as pd
    from yunesa.etl.load.supabase_loader import SupabaseLoader

    captured = {}

    class FakeTable:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self

        def execute(self):
            return None

    class FakeClient:
        def table(self, name):
            captured["table"] = name
            return FakeTable()

    loader = object.__new__(SupabaseLoader)
    loader.client = FakeClient()
    loader.key_role = "service_role"

    df = pd.DataFrame(
        [
            {
                "Title": "Paper A",
                "Year": "2026",
                "DOI": "10.1234/dup-doi",
                "Journal": "Journal A",
                "Document Type": "article",
            },
            {
                "Title": "Paper B",
                "Year": "2026",
                "DOI": "10.1234/dup-doi",
                "Journal": "Journal B",
                "Document Type": "article",
                "Abstract": "Abstract of B",
            },
        ]
    )

    count = loader.upsert_papers(df)

    # It should have deduplicated the rows by paper_id (using the DOI) in memory,
    # so only 1 record is sent to Supabase.
    assert count == 1
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["abstract"] == "Abstract of B"  # merged B's abstract into A


def test_scopus_processing_helper_cleans_and_deduplicates(monkeypatch):
    import pandas as pd
    import yunesa.etl.transform.cleaner as cleaner
    from yunesa.etl.clients.scopus_client import process_scopus_data

    monkeypatch.setattr(cleaner, "_load_lecturer_db", lambda: ({}, {}))

    df = pd.DataFrame(
        [
            {
                "Title": " Sample Paper ",
                "Year": "2026",
                "DOI": "10.1/sample",
                "Authors": "Doe, John",
                "Author IDs": "123",
                "Abstract": "Abstract: This is a sample.",
                "Keywords": "AI",
            },
            {
                "Title": "Sample Paper",
                "Year": "2026",
                "DOI": "10.1/sample",
                "Authors": "Doe, John",
                "Author IDs": "123",
            },
        ]
    )

    processed = process_scopus_data(df)

    assert len(processed) == 1
    assert processed.iloc[0]["Title"] == "Sample Paper"
    assert processed.iloc[0]["source"] == "scopus"
    assert "TLDR" in processed.columns


def test_scopus_processing_skips_empty_raw_csv(monkeypatch, tmp_path):
    import yunesa.etl.services.unesa_papers as service

    raw_path = tmp_path / "empty_scopus_raw.csv"
    master_path = tmp_path / "sample_scopus.csv"
    raw_path.write_text("", encoding="utf-8")

    result = service.run_scopus_processing(
        input_raw_path=raw_path,
        output_master_path=master_path,
    )

    assert result.empty
    assert not raw_path.exists()
    assert not master_path.exists()


def test_paper_extract_skips_when_checkpoint_is_fresh(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from yunesa.etl.pipelines import unesa_papers as pipeline

    class Config:
        is_full = False
        is_sample = False

    monkeypatch.setattr(pipeline, "ETL_FORCE_EXTRACT", False)
    monkeypatch.setattr(pipeline, "ETL_FRESHNESS_HOURS", 72)
    monkeypatch.setattr(pipeline, "path_exists", lambda path: path == "scopus.csv")
    monkeypatch.setattr(
        pipeline,
        "get_modification_time",
        lambda path: datetime.now(timezone.utc) - timedelta(hours=12),
    )

    assert pipeline._should_skip_extract(
        Config(),
        "paper_extract_scopus",
        ("scopus_raw.csv", "scopus.csv"),
    ) is True


def test_paper_enrichment_resumes_completed_checkpoint(monkeypatch):
    import pandas as pd
    import yunesa.etl.services.unesa_papers as service

    input_path = "paper_transformed.csv"
    output_path = "paper_enriched.csv"
    transformed = pd.DataFrame(
        [
            {"Title": "Completed Paper", "Abstract": "raw completed", "enriched": ""},
            {"Title": "Pending Paper", "Abstract": "raw pending", "enriched": ""},
        ]
    )
    checkpoint = pd.DataFrame(
        [
            {
                "Title": "Completed Paper",
                "Abstract": "enriched abstract",
                "Keywords": "knowledge graph; metadata",
                "Author IDs": "S123",
                "TLDR": "Completed TLDR.",
                "Document Type": "article",
                "enrichment_status": "complete",
                "enriched": "True",
            },
            {
                "Title": "Pending Paper",
                "Abstract": "old pending",
                "Keywords": "",
                "Author IDs": "",
                "TLDR": "",
                "Document Type": "",
                "enrichment_status": "partial",
                "enriched": "",
            },
        ]
    )
    reads = {input_path: transformed, output_path: checkpoint}
    written = []
    enriched_titles = []

    def fake_read(path, **kwargs):
        return reads[path].copy()

    def fake_write(df, path, **kwargs):
        written.append((path, df.copy()))

    def fake_enrich(df, batch_size, start_idx=0, allow_paid_proxy=False):
        pending = df[df["Title"] == "Pending Paper"]
        enriched_titles.extend(pending["Title"].tolist())
        for index in pending.index[:batch_size]:
            df.at[index, "Keywords"] = "pipeline; test"
            df.at[index, "Author IDs"] = "S456"
            df.at[index, "TLDR"] = "Pending TLDR."
            df.at[index, "enrichment_status"] = "complete"
            df.at[index, "enriched"] = "True"
        return df

    monkeypatch.setattr(service, "smart_exists", lambda path: path in reads)
    monkeypatch.setattr(service, "read_dataframe_artifact", fake_read)
    monkeypatch.setattr(service, "write_dataframe_artifact", fake_write)
    monkeypatch.setattr(service, "enrich_paper_batch", fake_enrich)
    monkeypatch.setattr(service, "ETL_ENRICH_MAX_PAPERS_PER_RUN", 0)

    result = service.run_paper_enrichment(
        input_csv=input_path,
        output_csv=output_path,
        allow_paid_proxy=False,
    )

    assert enriched_titles == ["Pending Paper"]
    assert result.loc[result["Title"] == "Completed Paper", "TLDR"].item() == "Completed TLDR."
    assert result.loc[result["Title"] == "Pending Paper", "TLDR"].item() == "Pending TLDR."
    assert written


def test_paper_supabase_insert_combines_scopus_and_scholar(monkeypatch):
    import pandas as pd
    import yunesa.etl.clients.postgres_client as pg_module
    import yunesa.etl.services.unesa_papers as service
    import yunesa.etl.transform.cleaner as cleaner
    import yunesa.etl.transform.deduplicator as deduplicator

    captured = {}

    def fake_exists(path):
        return path in {service.SCOPUS_CSV, service.SCHOLAR_CSV}

    def fake_read(path, **kwargs):
        if path == service.SCOPUS_CSV:
            return pd.DataFrame(
                [{
                    "Title": "Scopus Paper",
                    "Year": "2026",
                    "DOI": "10.1/scopus",
                    "Abstract": "Scopus abstract",
                    "Keywords": "scopus; metadata",
                    "Author IDs": "S1",
                    "TLDR": "Scopus TLDR.",
                }]
            )
        return pd.DataFrame(
            [{
                "Title": "Scholar Paper",
                "Year": "2026",
                "DOI": "",
                "scholar_id": "abc",
                "Abstract": "Scholar abstract",
                "Keywords": "scholar; metadata",
                "Author IDs": "S2",
                "TLDR": "Scholar TLDR.",
            }]
        )

    class FakePostgresClient:
        def upsert_papers(self, df):
            captured["paper_titles"] = set(df["Title"].tolist())
            return len(df)

    monkeypatch.setattr(service, "smart_exists", fake_exists)
    monkeypatch.setattr(service, "read_dataframe_artifact", fake_read)
    monkeypatch.setattr(cleaner, "clean_papers_batch", lambda df: df)
    monkeypatch.setattr(deduplicator, "deduplicate_papers", lambda df: df)
    monkeypatch.setattr(pg_module, "PostgresClient", lambda: FakePostgresClient())

    result = service.run_supabase_insert()

    assert result == {"papers": 2, "links": 0}
    assert captured["paper_titles"] == {"Scopus Paper", "Scholar Paper"}


def test_paper_supabase_insert_skips_incomplete_rows(monkeypatch):
    import pandas as pd
    import yunesa.etl.clients.postgres_client as pg_module
    import yunesa.etl.services.unesa_papers as service
    import yunesa.etl.transform.cleaner as cleaner
    import yunesa.etl.transform.deduplicator as deduplicator

    captured = {"upsert_called": False}

    def fake_read(path, **kwargs):
        return pd.DataFrame(
            [{
                "Title": "Incomplete Paper",
                "Abstract": "Has abstract",
                "Keywords": "",
                "Author IDs": "S1",
                "TLDR": "Has TLDR.",
            }]
        )

    class FakePostgresClient:
        def upsert_papers(self, df):
            captured["upsert_called"] = True
            return len(df)

    monkeypatch.setattr(service, "smart_exists", lambda path: path == "input.csv")
    monkeypatch.setattr(service, "read_dataframe_artifact", fake_read)
    monkeypatch.setattr(cleaner, "clean_papers_batch", lambda df: df)
    monkeypatch.setattr(deduplicator, "deduplicate_papers", lambda df: df)
    monkeypatch.setattr(pg_module, "PostgresClient", lambda: FakePostgresClient())

    result = service.run_supabase_insert(input_master_path="input.csv")

    assert result == {"papers": 0, "links": 0}
    assert captured["upsert_called"] is False


def test_deduplicate_papers_merges_author_relationships():
    import pandas as pd
    from yunesa.etl.transform.deduplicator import deduplicate_papers

    df = pd.DataFrame(
        [
            {"Title": "Same Paper", "Authors": "A", "Author IDs": "S1", "source": "scopus"},
            {"Title": "Same Paper", "Authors": "B", "Author IDs": "S2", "source": "scholar"},
        ]
    )

    result = deduplicate_papers(df)

    assert len(result) == 1
    assert result.loc[0, "Author IDs"] == "S1; S2"
    assert result.loc[0, "Authors"] == "A; B"
    assert result.loc[0, "source"] == "scopus; scholar"


def test_lecturers_service_functions_importable():
    from yunesa.etl.services.unesa_lecturers import (
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
    from yunesa.etl.services.siakadu_identity import enrich_with_siakadu, fetch_siakadu_data

    assert callable(fetch_siakadu_data)
    assert callable(enrich_with_siakadu)


def test_etl_path_modules_importable():
    from yunesa.etl.services.lecturer_paths import FINAL_CSV, SCRAPE_SIAKADU_PATH
    from yunesa.etl.services.paper_paths import PAPER_ENRICHMENT_STATE_JSON, SCHOLAR_CSV, SCOPUS_CSV

    assert FINAL_CSV is not None
    assert SCRAPE_SIAKADU_PATH is not None
    assert str(SCOPUS_CSV).endswith(".parquet")
    assert str(SCHOLAR_CSV).endswith(".parquet")
    assert str(PAPER_ENRICHMENT_STATE_JSON).endswith(".json")


def test_lecturer_downstream_tasks_do_not_skip_on_fresh_outputs(monkeypatch):
    import pandas as pd
    from yunesa.etl.pipelines import unesa_lecturers as pipeline
    import yunesa.etl.services.unesa_lecturers as lecturer_service

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
    from yunesa.etl.clients.scholar_client import ScholarVerificationClient

    client = ScholarVerificationClient(proxy_url="")
    assert callable(client.verify_batch)


def test_storage_compatibility_helpers_importable(tmp_path):
    import pandas as pd
    from yunesa.etl.utils.storage import (
        get_path_obj,
        normalize_storage_path,
        path_name,
        read_dataframe_artifact,
        read_json_artifact,
        smart_exists,
        smart_unlink,
        write_dataframe_artifact,
        write_json_artifact,
    )

    target = get_path_obj(tmp_path, "sample.csv")
    assert path_name(target) == "sample.csv"
    assert smart_exists(target) is False
    smart_unlink(target)
    assert get_path_obj("s3://bucket/prefix", "sample.csv") == "s3://bucket/prefix/sample.csv"
    assert normalize_storage_path("s3:/bucket/prefix/sample.csv") == "s3://bucket/prefix/sample.csv"
    assert path_name("s3://bucket/prefix/sample.csv") == "sample.csv"

    parquet_target = get_path_obj(tmp_path, "sample.parquet")
    state_target = get_path_obj(tmp_path, "checkpoint.json")
    write_dataframe_artifact(pd.DataFrame([{"title": "Paper A", "year": "2026"}]), parquet_target)
    write_json_artifact({"status": "running", "rows": 1}, state_target)

    assert read_dataframe_artifact(parquet_target).to_dict("records") == [
        {"title": "Paper A", "year": "2026"}
    ]
    assert read_json_artifact(state_target) == {"rows": 1, "status": "running"}


def test_siakadu_parser_extracts_lecturer_identities_only():
    from yunesa.etl.clients.siakadu_client import SiakaduClient

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
    import yunesa.etl.services.siakadu_identity as service

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
    import yunesa.etl.clients.keyword_scraper as keyword_scraper

    assert callable(keyword_scraper.enrich_single_paper)


def test_ieee_keyword_fallback_uses_controlled_vocabulary():
    from yunesa.etl.transform.ieee_keywords import (
        IeeeKeywordTerm,
        generate_ieee_keywords,
    )

    terms = (
        IeeeKeywordTerm(
            canonical="Knowledge graphs",
            aliases=("knowledge graph", "knowledge graphs"),
        ),
        IeeeKeywordTerm(
            canonical="Natural language processing",
            aliases=("natural language processing", "NLP"),
        ),
        IeeeKeywordTerm(
            canonical="Computer vision",
            aliases=("computer vision",),
        ),
    )

    keywords = generate_ieee_keywords(
        title="Academic knowledge graph construction",
        abstract="This study uses NLP for academic knowledge graph enrichment.",
        terms=terms,
    )

    assert keywords == "Knowledge graphs, Natural language processing"


def test_config_module_loads():
    from yunesa.etl.config import (
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
