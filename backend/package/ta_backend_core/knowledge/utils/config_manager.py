import os
import yaml
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class ConfigDict(dict):
    """A dictionary that allows dot-notation access to its keys."""
    def __getattr__(self, item):
        try:
            value = self[item]
            if isinstance(value, dict):
                return ConfigDict(value)
            return value
        except KeyError:
            return None

    def __setattr__(self, key, value):
        self[key] = value

class ConfigManager:
    """
    Universal Configuration Loader.
    Standard Implementation for UNESA Knowledge Graph Pipeline.
    """
    def __init__(self, config_name: str):
        self.config_name = config_name
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        self.config_dir = self.base_dir / "configs"
        self.env_path = self.base_dir / ".env"
        
        # Load .env first
        load_dotenv(self.env_path)
        
        # Load YAML
        self._raw_config = self._load_yaml()
        
        # Convert to Dot-Notation Dict
        self.config = ConfigDict(self._raw_config)
        
        # Apply Environment Overrides
        self._apply_env_overrides()

    def _load_yaml(self) -> dict:
        yaml_file = self.config_dir / f"{self.config_name}.yaml"
        if not yaml_file.exists():
            logger.warning(f"Config file {yaml_file} not found. Using empty defaults.")
            return {}
        
        try:
            with open(yaml_file, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading YAML {yaml_file}: {e}")
            return {}

    def _apply_env_overrides(self):
        """
        Scans all environment variables and applies those matching 
        the pattern: {MODULE}_{KEY} (e.g., ETL_SUPABASE_URL).
        """
        prefix = f"{self.config_name.upper()}_"
        for key, value in os.environ.items():
            # Support both prefixed (ETL_X) and global (X) for common keys
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower()
                self._update_deep(self.config, config_key, value)
            
            # Global fallbacks for common infra keys (NEO4J, SUPABASE, etc)
            common_keys = ["NEO4J", "SUPABASE", "OPENROUTER", "GROQ", "WEAVIATE", "HF_TOKEN", "OPIK"]
            for common in common_keys:
                if key.startswith(common):
                    self._update_deep(self.config, key.lower(), value)

    def _update_deep(self, d, key_path, value):
        """Helper to update nested dicts using snake_case or underscore paths."""
        # Simple implementation for flat keys for now
        # Can be expanded for nested key overrides if needed (e.g. DATABASE_PORT)
        d[key_path] = value

def load_config(name: str) -> ConfigDict:
    """Convenience function to load a config by name."""
    manager = ConfigManager(name)
    return manager.config
