from yunesa.knowledge.base import KBNotFoundError, KnowledgeBase
from yunesa.utils import logger


class KnowledgeBaseFactory:
    """Knowledge base factory class responsible for creating instances by type."""

    # Registered knowledge base type mapping {kb_type: kb_class}
    _kb_types: dict[str, type[KnowledgeBase]] = {}

    # Default config per type
    _default_configs: dict[str, dict] = {}

    @classmethod
    def register(cls, kb_type: str, kb_class: type[KnowledgeBase], default_config: dict = None):
        """
        Register a knowledge base type.

        Args:
            kb_type: Knowledge base type identifier.
            kb_class: Knowledge base class.
            default_config: Default config.
        """
        if not issubclass(kb_class, KnowledgeBase):
            raise ValueError(
                "Knowledge base class must inherit from KnowledgeBase")

        cls._kb_types[kb_type] = kb_class
        cls._default_configs[kb_type] = default_config or {}
        # logger.info(f"Registered knowledge base type: {kb_type}")

    @classmethod
    def create(cls, kb_type: str, work_dir: str, **kwargs) -> KnowledgeBase:
        """
        Create a knowledge base instance.

        Args:
            kb_type: Knowledge base type.
            work_dir: Working directory.
            **kwargs: Other initialization parameters.

        Returns:
            Knowledge base instance.

        Raises:
            KBNotFoundError: Unknown knowledge base type.
        """
        if kb_type not in cls._kb_types:
            available_types = list(cls._kb_types.keys())
            raise KBNotFoundError(
                f"Unknown knowledge base type: {kb_type}. Available types: {available_types}")

        kb_class = cls._kb_types[kb_type]

        # Merge default config and user config.
        config = cls._default_configs[kb_type].copy()
        config.update(kwargs)

        try:
            # Create instance
            instance = kb_class(work_dir, **config)
            logger.info(
                f"Created {kb_type} knowledge base instance at {work_dir}")
            return instance
        except Exception as e:
            logger.error(f"Failed to create {kb_type} knowledge base: {e}")
            raise

    @classmethod
    def get_available_types(cls) -> dict[str, dict]:
        """
        Get all available knowledge base types.

        Returns:
            Knowledge base type information dictionary.
        """
        result = {}
        for kb_type, kb_class in cls._kb_types.items():
            result[kb_type] = {
                "class_name": kb_class.__name__,
                "description": kb_class.__doc__ or "",
                "default_config": cls._default_configs[kb_type],
            }
        return result

    @classmethod
    def is_type_supported(cls, kb_type: str) -> bool:
        """
        Check whether the specified knowledge base type is supported.

        Args:
            kb_type: Knowledge base type.

        Returns:
            Whether it is supported.
        """
        return kb_type in cls._kb_types

    @classmethod
    def get_default_config(cls, kb_type: str) -> dict:
        """
        Get default config for the specified type.

        Args:
            kb_type: Knowledge base type.

        Returns:
            Default config dictionary.
        """
        return cls._default_configs.get(kb_type, {}).copy()
