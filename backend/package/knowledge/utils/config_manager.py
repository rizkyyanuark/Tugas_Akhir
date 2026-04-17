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
        
        # Resiliently find the root directory that contains 'configs'
        current_dir = Path(__file__).resolve().parent
        self.base_dir = current_dir.parents[2] # Fallback
        
        while current_dir != current_dir.parent:
            if (current_dir / "configs").is_dir():
                self.base_dir = current_dir
                break
            current_dir = current_dir.parent
            
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
        # Try to find if the key matches a nested structure
        # e.g., 'crawler_headless' could be d['crawler']['headless']
        parts = key_path.split('_')
        
        # If it's a simple key, just set it
        if len(parts) == 1:
            d[key_path] = self._parse_value(value)
            return

        # Try to traverse the dictionary
        current = d
        for i, part in enumerate(parts[:-1]):
            # If the part exists as a key and it is a dict, go deeper
            if part in current and isinstance(current[part], dict):
                current = current[part]
            else:
                # If we can't find a nested dict, we stop and set the remaining as a flat key
                # This handles keys like 'supabase_url' remain flat if 'supabase' isn't a dict
                remaining_key = "_".join(parts[i:])
                current[remaining_key] = self._parse_value(value)
                return
        
        # Set the final part
        current[parts[-1]] = self._parse_value(value)

    def _parse_value(self, value):
        """Parse string environment variables into appropriate Python types."""
        if isinstance(value, str):
            if value.lower() in ('true', 'yes', 'on'):
                return True
            if value.lower() in ('false', 'no', 'off'):
                return False
            if value.lower() == 'none':
                return None
            try:
                if '.' in value:
                    return float(value)
                return int(value)
            except ValueError:
                return value
        return value

def load_config(name: str) -> ConfigDict:
    """Convenience function to load a config by name."""
    manager = ConfigManager(name)
    return manager.config
