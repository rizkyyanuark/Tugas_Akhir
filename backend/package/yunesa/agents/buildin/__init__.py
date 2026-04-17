import asyncio
import importlib
import inspect
from pathlib import Path

from server.utils.singleton import SingletonMeta
from yunesa.agents.base import BaseAgent
from yunesa.utils import logger


class AgentManager(metaclass=SingletonMeta):
    def __init__(self):
        self._classes = {}
        self._instances = {}  # Stores created agent instances.

    def register_agent(self, agent_class):
        self._classes[agent_class.__name__] = agent_class

    def init_all_agents(self):
        for agent_id in self._classes.keys():
            self.get_agent(agent_id)

    def get_agent(self, agent_id, reload=False, reload_graph=False, **kwargs):
        # Check whether an instance for this agent already exists.
        if reload or agent_id not in self._instances:
            agent_class = self._classes[agent_id]
            self._instances[agent_id] = agent_class()

        # If only graph reload is requested, clear graph cache.
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
        """Automatically discover and register all agents under yuxi/agents/buildin/.

        Traverse subdirectories under yuxi/agents/buildin/. If a subdirectory contains
        an __init__.py file, try importing and registering BaseAgent subclasses
        from that module. (Auto-import supports private agents.)
        """
        # Get the agents directory path.
        agents_dir = Path(__file__).parent

        # Traverse all subdirectories.
        for item in agents_dir.iterdir():
            # logger.info(f"Trying to import module: {item}")
            # Skip non-directories, common folder, __pycache__, etc.
            if not item.is_dir() or item.name.startswith("_"):
                continue

            # Check whether __init__.py exists.
            init_file = item / "__init__.py"
            if not init_file.exists():
                logger.warning(f"{item} is not a valid module")
                continue

            # Try importing the module.
            try:
                module_name = f"yunesa.agents.buildin.{item.name}"
                module = importlib.import_module(module_name)

                # Find all BaseAgent subclasses in the module.
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
# Auto-discover and register all agents.
agent_manager.auto_discover_agents()
agent_manager.init_all_agents()

__all__ = ["agent_manager"]


if __name__ == "__main__":
    pass
