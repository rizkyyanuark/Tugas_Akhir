import os
from pathlib import Path
import pytest
from knowledge.utils.config_manager import ConfigDict, ConfigManager, load_config


def test_config_dict_access():
    """Test dot-notation access for ConfigDict."""
    config = ConfigDict(
        {"database": {"host": "localhost", "port": 5432}, "api_key": "secret"})

    assert config.api_key == "secret"
    assert config.database.host == "localhost"
    assert config.database.port == 5432

    # Missing key returns None
    assert config.missing_key is None
    assert config.database.missing_nested is None


def test_config_manager_env_override(monkeypatch):
    """Test that environment variables successfully override config values."""
    # Set a fake environment variable that starts with the common 'SUPABASE' string
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("ETL_MODE", "fast")

    # Initialize ConfigManager with a fake config name 'etl'
    manager = ConfigManager("etl")

    # Ensure overrides are applied dynamically
    assert manager.config["supabase_url"] == "https://fake.supabase.co"
    assert manager.config["mode"] == "fast"


def test_missing_yaml_file_handled_gracefully():
    """Ensure asking for a missing configuration file doesn't crash the loader."""
    mgr = ConfigManager("this_file_does_not_exist_ever")
    # Returns an empty dict inherently combined with env vars
    assert type(mgr.config) == ConfigDict
