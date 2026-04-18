"""
应用configure模块

使用 Pydantic BaseModel 实现configuremanagement，支持：
- 从 TOML fileloaduserconfigure
- 仅saveusermodify过的configureitems
- defaultconfigure定义在代码中
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
    """应用configure类"""

    # ============================================================
    # basic configuration
    # ============================================================
    save_dir: str = Field(default="saves", description="Save directory")
    model_dir: str = Field(default="", description="本地modeldirectory")

    # ============================================================
    # 功能开关
    # ============================================================
    enable_reranker: bool = Field(default=False, description="Enable reranker")
    enable_content_guard: bool = Field(default=False, description="whetherenabledcontent审查")
    enable_content_guard_llm: bool = Field(default=False, description="whetherenabledLLMcontent审查")
    enable_web_search: bool = Field(default=False, description="whetherenabled网络search")

    # ============================================================
    # modelconfigure
    # ============================================================
    default_model: str = Field(
        default="siliconflow/Pro/MiniMaxAI/MiniMax-M2.5",
        description="Default chat model",
    )
    fast_model: str = Field(
        default="siliconflow/Pro/MiniMaxAI/MiniMax-M2.5",
        description="快速responsemodel",
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
        description="content审查LLMmodel",
    )

    # ============================================================
    # Agent Configuration
    # ============================================================
    default_agent_id: str = Field(default="ChatbotAgent", description="defaultagentID")

    # ============================================================
    # Sandbox configure
    # ============================================================
    sandbox_provider: str = Field(default="provisioner", description="沙箱提供者")
    sandbox_provisioner_url: str = Field(default="http://sandbox-provisioner:8002", description="沙箱service地址")
    sandbox_virtual_path_prefix: str = Field(default="/home/gem/user-data", description="沙箱userdirectory前缀")
    sandbox_exec_timeout_seconds: int = Field(default=180, description="沙箱executetimeouttime（秒）")
    sandbox_max_output_bytes: int = Field(default=262144, description="沙箱最大output字节数")
    sandbox_keepalive_interval_seconds: int = Field(default=30, description="沙箱保活间隔（秒）")

    # ============================================================
    # model信息（只读，不持久化）
    # ============================================================
    model_names: dict[str, ChatModelProvider] = Field(
        default_factory=lambda: DEFAULT_CHAT_MODEL_PROVIDERS.copy(),
        description="聊天model提供商configure",
        exclude=True,
    )
    embed_model_names: dict[str, EmbedModelInfo] = Field(
        default_factory=lambda: DEFAULT_EMBED_MODELS.copy(),
        description="embeddingmodelconfigure",
        exclude=True,
    )
    reranker_names: dict[str, RerankerInfo] = Field(
        default_factory=lambda: DEFAULT_RERANKERS.copy(),
        description="rerankermodelconfigure",
        exclude=True,
    )

    # ============================================================
    # 运row时status（不持久化）
    # ============================================================
    model_provider_status: dict[str, bool] = Field(
        default_factory=dict,
        description="model提供商可用status",
        exclude=True,
    )
    valuable_model_provider: list[str] = Field(
        default_factory=list,
        description="可用的model提供商list",
        exclude=True,
    )

    # 内部status
    _config_file: Path | None = PrivateAttr(default=None)
    _user_modified_fields: set[str] = PrivateAttr(default_factory=set)
    _modified_providers: set[str] = PrivateAttr(default_factory=set)  # 记录具体modify的model提供商

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
        """从 TOML fileloaduserconfigure"""
        if not self._config_file or not self._config_file.exists():
            logger.info(f"Config file not found, using defaults: {self._config_file}")
            return

        logger.info(f"Loading config from {self._config_file}")
        try:
            with open(self._config_file, "rb") as f:
                user_config = tomli.load(f)

            # 记录usermodify的字段
            self._user_modified_fields = set(user_config.keys())

            # updateconfigure
            for key, value in user_config.items():
                if key == "model_names":
                    # 特殊processmodelconfigure
                    self._load_model_names(value)
                elif hasattr(self, key):
                    setattr(self, key, value)
                else:
                    logger.warning(f"Unknown config key: {key}")

            # 确保defaultagent为 ChatbotAgent（兼容旧configure）
            if not self.default_agent_id:
                self.default_agent_id = "ChatbotAgent"
                logger.info("default_agent_id not set, using default: ChatbotAgent")

        except Exception as e:
            logger.error(f"Failed to load config from {self._config_file}: {e}")

    def _load_model_names(self, model_names_data: dict[str, Any]) -> None:
        """loaduser自定义的modelconfigure"""
        for provider, provider_data in (model_names_data or {}).items():
            try:
                if provider in self.model_names:
                    # merge现有提供商的configure
                    merged = self.model_names[provider].model_dump() | dict(provider_data or {})
                    self.model_names[provider] = ChatModelProvider(**merged)
                else:
                    # add新的提供商
                    self.model_names[provider] = ChatModelProvider(**provider_data)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skip invalid model provider config {provider}: {e}")

    def _load_custom_providers(self) -> None:
        """从独立的TOMLfileload自定义供应商configure"""
        custom_config_file = self._config_file.parent / "custom_providers.toml"

        if not custom_config_file.exists():
            logger.info(f"Custom providers config file not found: {custom_config_file}")
            return

        logger.info(f"Loading custom providers from {custom_config_file}")
        try:
            with open(custom_config_file, "rb") as f:
                custom_config = tomli.load(f)

            # load自定义供应商
            if "model_names" in custom_config:
                self._load_custom_model_providers(custom_config["model_names"])

        except Exception as e:
            logger.error(f"Failed to load custom providers from {custom_config_file}: {e}")

    def _load_custom_model_providers(self, providers_data: dict[str, Any]) -> None:
        """load自定义model供应商"""
        for provider, provider_data in (providers_data or {}).items():
            try:
                payload = dict(provider_data or {})
                payload["custom"] = True
                self.model_names[provider] = ChatModelProvider(**payload)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skip invalid custom provider {provider}: {e}")

    def _handle_environment(self) -> None:
        """processenvironment变量和运row时status"""
        # processmodeldirectory
        self.model_dir = os.environ.get("MODEL_DIR") or self.model_dir
        if self.model_dir:
            if os.path.exists(self.model_dir):
                logger.debug(f"Model directory ({self.model_dir}) contains: {os.listdir(self.model_dir)}")
            else:
                logger.debug(f"Model directory ({self.model_dir}) does not exist. If not configured, please ignore it.")

        # checkmodel提供商的environment变量
        self.model_provider_status = {}
        for provider, info in self.model_names.items():
            env_var = info.env

            if env_var == "NO_API_KEY":
                self.model_provider_status[provider] = True
            else:
                api_key = os.environ.get(env_var)
                # 如果get到的值与environment变量名不同，说明environment变量存在或configure了直接值
                self.model_provider_status[provider] = bool(api_key or info.custom)

        # check网络search
        if os.getenv("TAVILY_API_KEY"):
            self.enable_web_search = True

        # get可用的model提供商
        self.valuable_model_provider = [k for k, v in self.model_provider_status.items() if v]

        # process Sandbox configure
        self.sandbox_provider = (os.getenv("SANDBOX_PROVIDER") or self.sandbox_provider or "provisioner").strip()
        self.sandbox_provisioner_url = (
            os.getenv("SANDBOX_PROVISIONER_URL") or self.sandbox_provisioner_url or "http://sandbox-provisioner:8002"
        ).strip()
        self.sandbox_virtual_path_prefix = (
            os.getenv("SANDBOX_VIRTUAL_PATH_PREFIX") or self.sandbox_virtual_path_prefix or "/home/gem/user-data"
        ).strip()
        self.sandbox_exec_timeout_seconds = int(
            os.getenv("SANDBOX_EXEC_TIMEOUT_SECONDS") or self.sandbox_exec_timeout_seconds or 180
        )
        self.sandbox_max_output_bytes = int(
            os.getenv("SANDBOX_MAX_OUTPUT_BYTES") or self.sandbox_max_output_bytes or 262144
        )
        self.sandbox_keepalive_interval_seconds = int(
            os.getenv("SANDBOX_KEEPALIVE_INTERVAL_SECONDS") or self.sandbox_keepalive_interval_seconds or 30
        )

        # verify Sandbox configure
        if self.sandbox_provider.lower() != "provisioner":
            raise ValueError("Only sandbox_provider=provisioner is supported.")
        if not self.sandbox_provisioner_url:
            raise ValueError("SANDBOX_PROVISIONER_URL is required when sandbox provider is provisioner.")
        if not self.sandbox_virtual_path_prefix.startswith("/"):
            self.sandbox_virtual_path_prefix = f"/{self.sandbox_virtual_path_prefix}"

        if not self.valuable_model_provider:
            raise ValueError("No model provider available, please check your `.env` file.")

    def save(self) -> None:
        """saveconfigure到 TOML file（仅saveusermodify的字段）"""
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        logger.info(f"Saving config to {self._config_file}")

        # getdefaultconfigure
        default_config = Config.model_construct()

        # 对比当前configure和defaultconfigure，找出usermodify的字段
        user_modified = {}
        for field_name in self.model_fields.keys():
            # 跳过 exclude=True 的字段
            field_info = self.model_fields[field_name]
            if field_info.exclude:
                continue

            current_value = getattr(self, field_name)
            default_value = getattr(default_config, field_name)

            # 如果值不同，说明usermodify了
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
        """exportconfigure为字典（用于 API return）"""
        config_dict = self.model_dump(
            exclude={
                "model_names",
                "embed_model_names",
                "reranker_names",
                "model_provider_status",
                "valuable_model_provider",
            }
        )

        # addmodel信息（convert为字典format供前端使用）
        config_dict["model_names"] = {provider: info.model_dump() for provider, info in self.model_names.items()}
        config_dict["embed_model_names"] = {
            model_id: info.model_dump() for model_id, info in self.embed_model_names.items()
        }
        config_dict["reranker_names"] = {model_id: info.model_dump() for model_id, info in self.reranker_names.items()}

        # add运row时status信息
        config_dict["model_provider_status"] = self.model_provider_status
        config_dict["valuable_model_provider"] = self.valuable_model_provider

        fields_info = {}
        for field_name, field_info in Config.model_fields.items():
            if not field_info.exclude:  # 排除内部字段
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
        """get所有可用的聊天modellist"""
        choices = []
        for provider, info in self.model_names.items():
            if self.model_provider_status.get(provider, False):
                for model in info.models:
                    choices.append(f"{provider}/{model}")
        return choices

    def get_embed_model_choices(self) -> list[str]:
        """get所有可用的embeddingmodellist"""
        return list(self.embed_model_names.keys())

    def get_reranker_choices(self) -> list[str]:
        """get所有可用的rerankermodellist"""
        return list(self.reranker_names.keys())

    # ============================================================
    # 兼容旧代码的方法
    # ============================================================

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问 config[key]"""
        logger.warning("Using deprecated dict-style access for Config. Please use attribute access instead.")
        return getattr(self, key, None)

    def __setitem__(self, key: str, value: Any):
        """支持字典式赋值 config[key] = value"""
        logger.warning("Using deprecated dict-style assignment for Config. Please use attribute access instead.")
        setattr(self, key, value)

    def update(self, other: dict[str, Any]) -> None:
        """批量updateconfigure（兼容旧代码）"""
        for key, value in other.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"Unknown config key: {key}")

    def _save_models_to_file(self, provider_name: str | None = None) -> None:
        """savemodelconfigure到主configurefile

        Args:
            provider_name: 如果提供，只save特定provider的modify；否则save所有model_names
        """
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        logger.info(f"Saving models config to {self._config_file}")

        try:
            # read现有configure
            user_config = {}
            if self._config_file.exists():
                with open(self._config_file, "rb") as f:
                    user_config = tomli.load(f)

            # initialize model_names configure（如果does not exist）
            if "model_names" not in user_config:
                user_config["model_names"] = {}

            if provider_name:
                # 只save特定 provider 的modify
                if provider_name in self.model_names:
                    user_config["model_names"][provider_name] = self.model_names[provider_name].model_dump()
                    # 记录具体modify的 provider
                    self._modified_providers.add(provider_name)
                    logger.info(f"Saved models config for provider: {provider_name}")
            else:
                # save所有 model_names
                user_config["model_names"] = {
                    provider: info.model_dump() for provider, info in self.model_names.items()
                }
                # 记录整 model_names 字段的modify
                self._user_modified_fields.add("model_names")
                logger.info("Saved all models config")

            # writeconfigurefile
            with open(self._config_file, "wb") as f:
                tomli_w.dump(user_config, f)
            logger.info(f"Models config saved to {self._config_file}")
        except Exception as e:
            logger.error(f"Failed to save models config to {self._config_file}: {e}")

    # ============================================================
    # 自定义供应商management方法
    # ============================================================

    def add_custom_provider(self, provider_id: str, provider_data: dict[str, Any]) -> bool:
        """add自定义供应商

        Args:
            provider_id: 供应商unique identifier符
            provider_data: 供应商configuredata

        Returns:
            whetheraddsuccessful
        """
        try:
            # processenvironment变量，remove ${} 包裹
            if "env" in provider_data and provider_data["env"]:
                env_value = provider_data["env"]
                if isinstance(env_value, str) and env_value.startswith("${") and env_value.endswith("}"):
                    provider_data["env"] = env_value[2:-1]

            # 确保标记为自定义供应商
            provider_data["custom"] = True

            # check供应商IDwhetheralready exists（无论是内置还是自定义）
            if provider_id in self.model_names:
                logger.error(f"Provider ID already exists: {provider_id}")
                return False

            # add到configure中
            self.model_names[provider_id] = ChatModelProvider(**provider_data)

            # save到自定义供应商configurefile
            self._save_custom_providers()

            # 重新processenvironment变量
            self._handle_environment()

            logger.info(f"Added custom provider: {provider_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add custom provider {provider_id}: {e}")
            return False

    def update_custom_provider(self, provider_id: str, provider_data: dict) -> bool:
        """update自定义供应商

        Args:
            provider_id: 供应商unique identifier符
            provider_data: 新的供应商configuredata

        Returns:
            whetherupdatesuccessful
        """
        try:
            # processenvironment变量，remove ${} 包裹
            if "env" in provider_data and provider_data["env"]:
                env_value = provider_data["env"]
                if isinstance(env_value, str) and env_value.startswith("${") and env_value.endswith("}"):
                    provider_data["env"] = env_value[2:-1]

            # check供应商whether存在且为自定义供应商
            if provider_id not in self.model_names:
                logger.error(f"Provider not found: {provider_id}")
                return False

            if not self.model_names[provider_id].custom:
                logger.error(f"Cannot update non-custom provider: {provider_id}")
                return False

            # 确保保持自定义供应商标记
            provider_data["custom"] = True

            # update供应商configure
            self.model_names[provider_id] = ChatModelProvider(**provider_data)

            # save到自定义供应商configurefile
            self._save_custom_providers()

            # 重新processenvironment变量
            self._handle_environment()

            logger.info(f"Updated custom provider: {provider_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update custom provider {provider_id}: {e}")
            return False

    def delete_custom_provider(self, provider_id: str) -> bool:
        """delete自定义供应商

        Args:
            provider_id: 供应商unique identifier符

        Returns:
            whetherdeletesuccessful
        """
        try:
            # check供应商whether存在且为自定义供应商
            if provider_id not in self.model_names:
                logger.error(f"Provider not found: {provider_id}")
                return False

            if not self.model_names[provider_id].custom:
                logger.error(f"Cannot delete non-custom provider: {provider_id}")
                return False

            # 从configure中delete
            del self.model_names[provider_id]

            # save到自定义供应商configurefile
            self._save_custom_providers()

            # 重新processenvironment变量
            self._handle_environment()

            logger.info(f"Deleted custom provider: {provider_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete custom provider {provider_id}: {e}")
            return False

    def get_custom_providers(self) -> dict[str, ChatModelProvider]:
        """get所有自定义供应商

        Returns:
            自定义供应商字典
        """
        return {k: v for k, v in self.model_names.items() if v.custom}

    def _save_custom_providers(self) -> None:
        """save自定义供应商到独立configurefile"""
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        custom_config_file = self._config_file.parent / "custom_providers.toml"

        try:
            # get所有自定义供应商
            custom_providers = self.get_custom_providers()

            # createconfiguredata
            custom_config = {}
            if custom_providers:
                custom_config["model_names"] = {
                    provider: info.model_dump() for provider, info in custom_providers.items()
                }

            # 确保directory存在
            custom_config_file.parent.mkdir(parents=True, exist_ok=True)

            # writeconfigurefile
            with open(custom_config_file, "wb") as f:
                tomli_w.dump(custom_config, f)

            logger.info(f"Custom providers saved to {custom_config_file}")

        except Exception as e:
            logger.error(f"Failed to save custom providers to {custom_config_file}: {e}")


# 全局configure实例
config = Config()
