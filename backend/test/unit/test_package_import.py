import sys


def test_import_yunesa_does_not_eagerly_import_knowledge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sys.modules.pop("yunesa", None)
    sys.modules.pop("yunesa.knowledge", None)

    import yunesa

    assert yunesa.get_version() == "0.6.0"
    assert "yunesa.knowledge" not in sys.modules
