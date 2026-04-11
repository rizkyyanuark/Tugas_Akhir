import asyncio
import importlib
import inspect
from pathlib import Path

from ta_backend_core.assistant import config
from server.utils.singleton import SingletonMeta
from ta_backend_core.assistant.agents.base import BaseAgent
from ta_backend_core.assistant.utils import logger


class AgentManager(metaclass=SingletonMeta):
    def __init__(self):
        self._classes = {}
        self._instances = {}  # Store created agent instances

    def register_agent(self, agent_class):
        self._classes[agent_class.__name__] = agent_class

    def init_all_agents(self):
        for agent_id in self._classes.keys():
            self.get_agent(agent_id)

    def get_agent(self, agent_id, reload=False, reload_graph=False, **kwargs):
        # Check if an instance of this agent has already been created
        if reload or agent_id not in self._instances:
            agent_class = self._classes[agent_id]
            self.milvus_db = kwargs.get("milvus_db") or "ta_know"
            self._instances[agent_id] = agent_class()

        # If only reloading the graph is needed, clear the graph cache
        if reload_graph and agent_id in self._instances:
            self._instances[agent_id].reload_graph()

        return self._instances[agent_id]

    def get_agents(self):
        return list(self._instances.values())

    async def reload_all(self):
        for agent_id in self._classes.keys():
            self.get_agent(agent_id, reload=True)

    async def get_agents_info(self, include_configurable_items: bool = True):
        agents = self.get_agents()
        return await asyncio.gather(
            *[a.get_info(include_configurable_items=include_configurable_items) for a in agents]
        )

    def auto_discover_agents(self):
        """Automatically discover and register all agents under ta_backend_core.assistant.agents.buildin/.

        Iterates through all subfolders in the ta_backend_core/assistant/agents/buildin/ directory. If a subfolder contains __init__.py,
        it attempts to import subclasses of BaseAgent from it and registers them. (Supports private agents using auto-import).
        """
        # Get the path to the agents directory
        agents_dir = Path(__file__).parent

        # Iterate through all subdirectories
        for item in agents_dir.iterdir():
            # logger.info(f"Attempting to import module: {item}")
            # Skip non-directories, common directories, __pycache__, etc.
            if not item.is_dir() or item.name.startswith("_"):
                continue

            # Check for __init__.py file
            init_file = item / "__init__.py"
            if not init_file.exists():
                logger.warning(f"{item} is not a valid module")
                continue

            # Try to import module
            try:
                module_name = f"ta_backend_core.assistant.agents.buildin.{item.name}"
                module = importlib.import_module(module_name)

                # Find all subclasses of BaseAgent in the module
                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, BaseAgent)
                        and obj is not BaseAgent
                        and obj.__module__.startswith(module_name)
                    ):
                        logger.info(
                            f"Auto-discovered agent: {obj.__name__} from {item.name}")
                        self.register_agent(obj)

            except Exception as e:
                logger.warning(f"Failed to load agent from {item.name}: {e}")


agent_manager = AgentManager()
# Automatically discover and register all agents
agent_manager.auto_discover_agents()
agent_manager.init_all_agents()

__all__ = ["agent_manager"]


if __name__ == "__main__":
    pass
