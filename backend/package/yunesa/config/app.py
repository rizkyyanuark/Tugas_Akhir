"""
Application configuration module.

Uses Pydantic BaseModel to implement configuration management, supporting:
- Loading user configuration from TOML files
- Saving only user-modified configuration items
- Defining default configuration in code
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomli
import tomli_w
from pydantic import BaseModel, Field, PrivateAttr

from yunesa.config.static.models import (
    DEFAULT_CHAT_MODEL_PROVIDERS,
    DEFAULT_EMBED_MODELS,
    DEFAULT_RERANKERS,
    ChatModelProvider,
    EmbedModelInfo,
    RerankerInfo,
)
from yunesa.utils.logging_config import logger


class Config(BaseModel):
    """Application configuration class."""

    # ============================================================
    # basic configuration
    # ============================================================
    save_dir: str = Field(default="saves", description="Save directory")
    model_dir: str = Field(default="", description="Local model directory")

    # ============================================================
    # Feature flags
    # ============================================================
    enable_reranker: bool = Field(default=False, description="Enable reranker")
    enable_content_guard: bool = Field(
        default=False, description="Whether content guard is enabled")
    enable_content_guard_llm: bool = Field(
        default=False, description="Whether LLM content guard is enabled")
    enable_web_search: bool = Field(
        default=False, description="Whether web search is enabled")

    # ============================================================
    # Model configuration
    # ============================================================
    default_model: str = Field(
        default="siliconflow/Pro/MiniMaxAI/MiniMax-M2.5",
        description="Default chat model",
    )
    fast_model: str = Field(
        default="siliconflow/Pro/MiniMaxAI/MiniMax-M2.5",
        description="Fast response model",
    )
    embed_model: str = Field(
        default="siliconflow/Pro/BAAI/bge-m3",
        description="default Embedding model",
    )
    reranker: str = Field(
        default="siliconflow/Pro/BAAI/bge-reranker-v2-m3",
        description="default Re-Ranker model",
    )
    content_guard_llm_model: str = Field(
        default="siliconflow/Pro/MiniMaxAI/MiniMax-M2.5",
        description="Content guard LLM model",
    )

    # ============================================================
    # Agent Configuration
    # ============================================================
    default_agent_id: str = Field(
        default="ChatbotAgent", description="Default agent ID")

    # ============================================================
    # Sandbox configuration
    # ============================================================
    sandbox_provider: str = Field(
        default="provisioner", description="Sandbox provider")
    sandbox_provisioner_url: str = Field(
        default="http://sandbox-provisioner:8002", description="Sandbox service URL")
    sandbox_virtual_path_prefix: str = Field(
        default="/home/gem/user-data", description="Sandbox user directory prefix")
    sandbox_exec_timeout_seconds: int = Field(
        default=180, description="Sandbox execution timeout (seconds)")
    sandbox_max_output_bytes: int = Field(
        default=262144, description="Maximum sandbox output bytes")
    sandbox_keepalive_interval_seconds: int = Field(
        default=30, description="Sandbox keepalive interval (seconds)")

    # ============================================================
    # Model metadata (read-only, not persisted)
    # ============================================================
    model_names: dict[str, ChatModelProvider] = Field(
        default_factory=lambda: DEFAULT_CHAT_MODEL_PROVIDERS.copy(),
        description="Chat model provider configuration",
        exclude=True,
    )
    embed_model_names: dict[str, EmbedModelInfo] = Field(
        default_factory=lambda: DEFAULT_EMBED_MODELS.copy(),
        description="Embedding model configuration",
        exclude=True,
    )
    reranker_names: dict[str, RerankerInfo] = Field(
        default_factory=lambda: DEFAULT_RERANKERS.copy(),
        description="Reranker model configuration",
        exclude=True,
    )

    # ============================================================
    # Runtime status (not persisted)
    # ============================================================
    model_provider_status: dict[str, bool] = Field(
        default_factory=dict,
        description="Model provider availability status",
        exclude=True,
    )
    valuable_model_provider: list[str] = Field(
        default_factory=list,
        description="List of available model providers",
        exclude=True,
    )

    # Internal status
    _config_file: Path | None = PrivateAttr(default=None)
    _user_modified_fields: set[str] = PrivateAttr(default_factory=set)
    # Record specifically modified model providers
    _modified_providers: set[str] = PrivateAttr(default_factory=set)

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    def __init__(self, **data):
        super().__init__(**data)
        self._setup_paths()
        self._load_user_config()
        self._load_custom_providers()
        self._handle_environment()

    def _setup_paths(self) -> None:
        """Set config file paths"""
        self.save_dir = os.getenv("SAVE_DIR") or self.save_dir
        self._config_file = Path(self.save_dir) / "config" / "base.toml"
        self._config_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_user_config(self) -> None:
        """Load user configuration from a TOML file."""
        if not self._config_file or not self._config_file.exists():
            logger.info(
                f"Config file not found, using defaults: {self._config_file}")
            return

        logger.info(f"Loading config from {self._config_file}")
        try:
            with open(self._config_file, "rb") as f:
                user_config = tomli.load(f)

            # Record user-modified fields.
            self._user_modified_fields = set(user_config.keys())

            # Update configuration.
            for key, value in user_config.items():
                if key == "model_names":
                    # Special handling for model configuration.
                    self._load_model_names(value)
                elif hasattr(self, key):
                    setattr(self, key, value)
                else:
                    logger.warning(f"Unknown config key: {key}")

            # Ensure default agent is ChatbotAgent (backward compatibility).
            if not self.default_agent_id:
                self.default_agent_id = "ChatbotAgent"
                logger.info(
                    "default_agent_id not set, using default: ChatbotAgent")

        except Exception as e:
            logger.error(
                f"Failed to load config from {self._config_file}: {e}")

    def _load_model_names(self, model_names_data: dict[str, Any]) -> None:
        """Load user-defined model configuration."""
        for provider, provider_data in (model_names_data or {}).items():
            try:
                if provider in self.model_names:
                    # Merge existing provider configuration.
                    merged = self.model_names[provider].model_dump() | dict(
                        provider_data or {})
                    self.model_names[provider] = ChatModelProvider(**merged)
                else:
                    # Add a new provider.
                    self.model_names[provider] = ChatModelProvider(
                        **provider_data)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Skip invalid model provider config {provider}: {e}")

    def _load_custom_providers(self) -> None:
        """Load custom provider configuration from a standalone TOML file."""
        custom_config_file = self._config_file.parent / "custom_providers.toml"

        if not custom_config_file.exists():
            logger.info(
                f"Custom providers config file not found: {custom_config_file}")
            return

        logger.info(f"Loading custom providers from {custom_config_file}")
        try:
            with open(custom_config_file, "rb") as f:
                custom_config = tomli.load(f)

            # Load custom providers.
            if "model_names" in custom_config:
                self._load_custom_model_providers(custom_config["model_names"])

        except Exception as e:
            logger.error(
                f"Failed to load custom providers from {custom_config_file}: {e}")

    def _load_custom_model_providers(self, providers_data: dict[str, Any]) -> None:
        """Load custom model providers."""
        for provider, provider_data in (providers_data or {}).items():
            try:
                payload = dict(provider_data or {})
                payload["custom"] = True
                self.model_names[provider] = ChatModelProvider(**payload)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skip invalid custom provider {provider}: {e}")

    def _handle_environment(self) -> None:
        """Process environment variables and runtime status."""
        # Process model directory.
        self.model_dir = os.environ.get("MODEL_DIR") or self.model_dir
        if self.model_dir:
            if os.path.exists(self.model_dir):
                logger.debug(
                    f"Model directory ({self.model_dir}) contains: {os.listdir(self.model_dir)}")
            else:
                logger.debug(
                    f"Model directory ({self.model_dir}) does not exist. If not configured, please ignore it.")

        # Check model provider environment variables.
        self.model_provider_status = {}
        for provider, info in self.model_names.items():
            env_var = info.env

            if env_var == "NO_API_KEY":
                self.model_provider_status[provider] = True
            else:
                api_key = os.environ.get(env_var)
                # If a value is found, the environment variable exists or a direct value is configured.
                self.model_provider_status[provider] = bool(
                    api_key or info.custom)

            # Check web search availability.
        if os.getenv("TAVILY_API_KEY"):
            self.enable_web_search = True

            # Get available model providers.
        self.valuable_model_provider = [
            k for k, v in self.model_provider_status.items() if v]

        # process Sandbox configure
        self.sandbox_provider = (os.getenv(
            "SANDBOX_PROVIDER") or self.sandbox_provider or "provisioner").strip()
        self.sandbox_provisioner_url = (
            os.getenv(
                "SANDBOX_PROVISIONER_URL") or self.sandbox_provisioner_url or "http://sandbox-provisioner:8002"
        ).strip()
        self.sandbox_virtual_path_prefix = (
            os.getenv(
                "SANDBOX_VIRTUAL_PATH_PREFIX") or self.sandbox_virtual_path_prefix or "/home/gem/user-data"
        ).strip()
        self.sandbox_exec_timeout_seconds = int(
            os.getenv(
                "SANDBOX_EXEC_TIMEOUT_SECONDS") or self.sandbox_exec_timeout_seconds or 180
        )
        self.sandbox_max_output_bytes = int(
            os.getenv(
                "SANDBOX_MAX_OUTPUT_BYTES") or self.sandbox_max_output_bytes or 262144
        )
        self.sandbox_keepalive_interval_seconds = int(
            os.getenv(
                "SANDBOX_KEEPALIVE_INTERVAL_SECONDS") or self.sandbox_keepalive_interval_seconds or 30
        )

        # verify Sandbox configure
        if self.sandbox_provider.lower() != "provisioner":
            raise ValueError("Only sandbox_provider=provisioner is supported.")
        if not self.sandbox_provisioner_url:
            raise ValueError(
                "SANDBOX_PROVISIONER_URL is required when sandbox provider is provisioner.")
        if not self.sandbox_virtual_path_prefix.startswith("/"):
            self.sandbox_virtual_path_prefix = f"/{self.sandbox_virtual_path_prefix}"

        if not self.valuable_model_provider:
            raise ValueError(
                "No model provider available, please check your `.env` file.")

    def save(self) -> None:
        """Save configuration to a TOML file (only user-modified fields)."""
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        logger.info(f"Saving config to {self._config_file}")

        # Get default configuration.
        default_config = Config.model_construct()

        # Compare current and default configuration to find user-modified fields.
        user_modified = {}
        for field_name in self.model_fields.keys():
            # Skip fields marked as exclude=True.
            field_info = self.model_fields[field_name]
            if field_info.exclude:
                continue

            current_value = getattr(self, field_name)
            default_value = getattr(default_config, field_name)

            # If values differ, the field was modified by the user.
            if current_value != default_value:
                user_modified[field_name] = current_value

        # write TOML file
        try:
            with open(self._config_file, "wb") as f:
                tomli_w.dump(user_modified, f)
            logger.info(f"Config saved to {self._config_file}")
        except Exception as e:
            logger.error(f"Failed to save config to {self._config_file}: {e}")

    def dump_config(self) -> dict[str, Any]:
        """Export configuration as a dictionary (for API responses)."""
        config_dict = self.model_dump(
            exclude={
                "model_names",
                "embed_model_names",
                "reranker_names",
                "model_provider_status",
                "valuable_model_provider",
            }
        )

        # Add model information (converted to dict format for frontend use).
        config_dict["model_names"] = {provider: info.model_dump(
        ) for provider, info in self.model_names.items()}
        config_dict["embed_model_names"] = {
            model_id: info.model_dump() for model_id, info in self.embed_model_names.items()
        }
        config_dict["reranker_names"] = {model_id: info.model_dump(
        ) for model_id, info in self.reranker_names.items()}

        # Add runtime status information.
        config_dict["model_provider_status"] = self.model_provider_status
        config_dict["valuable_model_provider"] = self.valuable_model_provider

        fields_info = {}
        for field_name, field_info in Config.model_fields.items():
            if not field_info.exclude:  # Exclude internal fields.
                fields_info[field_name] = {
                    "des": field_info.description,
                    "default": field_info.default,
                    "type": field_info.annotation.__name__
                    if hasattr(field_info.annotation, "__name__")
                    else str(field_info.annotation),
                    "exclude": field_info.exclude if hasattr(field_info, "exclude") else False,
                }
        config_dict["_config_items"] = fields_info

        return config_dict

    def get_model_choices(self) -> list[str]:
        """Get all available chat model choices."""
        choices = []
        for provider, info in self.model_names.items():
            if self.model_provider_status.get(provider, False):
                for model in info.models:
                    choices.append(f"{provider}/{model}")
        return choices

    def get_embed_model_choices(self) -> list[str]:
        """Get all available embedding model choices."""
        return list(self.embed_model_names.keys())

    def get_reranker_choices(self) -> list[str]:
        """Get all available reranker model choices."""
        return list(self.reranker_names.keys())

    # ============================================================
    # Backward compatibility methods
    # ============================================================

    def __getitem__(self, key: str) -> Any:
        """Support dict-style access: config[key]."""
        logger.warning(
            "Using deprecated dict-style access for Config. Please use attribute access instead.")
        return getattr(self, key, None)

    def __setitem__(self, key: str, value: Any):
        """Support dict-style assignment: config[key] = value."""
        logger.warning(
            "Using deprecated dict-style assignment for Config. Please use attribute access instead.")
        setattr(self, key, value)

    def update(self, other: dict[str, Any]) -> None:
        """Batch update configuration (backward compatibility)."""
        for key, value in other.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"Unknown config key: {key}")

    def _save_models_to_file(self, provider_name: str | None = None) -> None:
        """Save model configuration to the main config file.

        Args:
            provider_name: If provided, save only changes for that provider; otherwise save all model_names.
        """
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        logger.info(f"Saving models config to {self._config_file}")

        try:
            # Read existing configuration.
            user_config = {}
            if self._config_file.exists():
                with open(self._config_file, "rb") as f:
                    user_config = tomli.load(f)

            # Initialize model_names configuration (if it does not exist).
            if "model_names" not in user_config:
                user_config["model_names"] = {}

            if provider_name:
                # Save only changes for a specific provider.
                if provider_name in self.model_names:
                    user_config["model_names"][provider_name] = self.model_names[provider_name].model_dump(
                    )
                    # Record specifically modified provider.
                    self._modified_providers.add(provider_name)
                    logger.info(
                        f"Saved models config for provider: {provider_name}")
            else:
                # Save all model_names.
                user_config["model_names"] = {
                    provider: info.model_dump() for provider, info in self.model_names.items()
                }
                # Record modification of the model_names field.
                self._user_modified_fields.add("model_names")
                logger.info("Saved all models config")

            # Write config file.
            with open(self._config_file, "wb") as f:
                tomli_w.dump(user_config, f)
            logger.info(f"Models config saved to {self._config_file}")
        except Exception as e:
            logger.error(
                f"Failed to save models config to {self._config_file}: {e}")

    # ============================================================
    # Custom provider management methods
    # ============================================================

    def add_custom_provider(self, provider_id: str, provider_data: dict[str, Any]) -> bool:
        """Add a custom provider.

        Args:
            provider_id: Provider unique identifier.
            provider_data: Provider configuration data.

        Returns:
            Whether the add operation was successful.
        """
        try:
            # Process environment variable value by removing ${} wrapper.
            if "env" in provider_data and provider_data["env"]:
                env_value = provider_data["env"]
                if isinstance(env_value, str) and env_value.startswith("${") and env_value.endswith("}"):
                    provider_data["env"] = env_value[2:-1]

            # Ensure it is marked as a custom provider.
            provider_data["custom"] = True

            # Check whether provider ID already exists (built-in or custom).
            if provider_id in self.model_names:
                logger.error(f"Provider ID already exists: {provider_id}")
                return False

            # Add to configuration.
            self.model_names[provider_id] = ChatModelProvider(**provider_data)

            # Save to custom provider config file.
            self._save_custom_providers()

            # Re-process environment variables.
            self._handle_environment()

            logger.info(f"Added custom provider: {provider_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add custom provider {provider_id}: {e}")
            return False

    def update_custom_provider(self, provider_id: str, provider_data: dict) -> bool:
        """Update a custom provider.

        Args:
            provider_id: Provider unique identifier.
            provider_data: New provider configuration data.

        Returns:
            Whether the update operation was successful.
        """
        try:
            # Process environment variable value by removing ${} wrapper.
            if "env" in provider_data and provider_data["env"]:
                env_value = provider_data["env"]
                if isinstance(env_value, str) and env_value.startswith("${") and env_value.endswith("}"):
                    provider_data["env"] = env_value[2:-1]

            # Check whether provider exists and is custom.
            if provider_id not in self.model_names:
                logger.error(f"Provider not found: {provider_id}")
                return False

            if not self.model_names[provider_id].custom:
                logger.error(
                    f"Cannot update non-custom provider: {provider_id}")
                return False

            # Ensure custom provider marker is preserved.
            provider_data["custom"] = True

            # Update provider configuration.
            self.model_names[provider_id] = ChatModelProvider(**provider_data)

            # Save to custom provider config file.
            self._save_custom_providers()

            # Re-process environment variables.
            self._handle_environment()

            logger.info(f"Updated custom provider: {provider_id}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to update custom provider {provider_id}: {e}")
            return False

    def delete_custom_provider(self, provider_id: str) -> bool:
        """Delete a custom provider.

        Args:
            provider_id: Provider unique identifier.

        Returns:
            Whether the delete operation was successful.
        """
        try:
            # Check whether provider exists and is custom.
            if provider_id not in self.model_names:
                logger.error(f"Provider not found: {provider_id}")
                return False

            if not self.model_names[provider_id].custom:
                logger.error(
                    f"Cannot delete non-custom provider: {provider_id}")
                return False

            # Delete from configuration.
            del self.model_names[provider_id]

            # Save to custom provider config file.
            self._save_custom_providers()

            # Re-process environment variables.
            self._handle_environment()

            logger.info(f"Deleted custom provider: {provider_id}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to delete custom provider {provider_id}: {e}")
            return False

    def get_custom_providers(self) -> dict[str, ChatModelProvider]:
        """Get all custom providers.

        Returns:
            Dictionary of custom providers.
        """
        return {k: v for k, v in self.model_names.items() if v.custom}

    def _save_custom_providers(self) -> None:
        """Save custom providers to a standalone config file."""
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        custom_config_file = self._config_file.parent / "custom_providers.toml"

        try:
            # Get all custom providers.
            custom_providers = self.get_custom_providers()

            # Create configuration data.
            custom_config = {}
            if custom_providers:
                custom_config["model_names"] = {
                    provider: info.model_dump() for provider, info in custom_providers.items()
                }

            # Ensure target directory exists.
            custom_config_file.parent.mkdir(parents=True, exist_ok=True)

            # Write config file.
            with open(custom_config_file, "wb") as f:
                tomli_w.dump(custom_config, f)

            logger.info(f"Custom providers saved to {custom_config_file}")

        except Exception as e:
            logger.error(
                f"Failed to save custom providers to {custom_config_file}: {e}")


# Global configuration instance
config = Config()
