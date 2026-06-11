import os

from fastapi import APIRouter

from server.routers.auth_router import auth
from server.routers.chat_router import chat
from server.routers.dashboard_router import dashboard
from server.routers.department_router import department
from server.routers.mcp_router import mcp
from server.routers.skill_router import skills
from server.routers.subagent_router import subagents_router
from server.routers.system_router import system
from server.routers.task_router import tasks
from server.routers.tool_router import tools
from server.routers.apikey_router import apikey_router

_LITE_MODE = os.environ.get("LITE_MODE", "").lower() in ("true", "1")

router = APIRouter()

# Core system interfaces: health checks, configuration, authentication, and chat.
router.include_router(system)  # /api/system/* system status and global configuration
router.include_router(auth)  # /api/auth/* login and user profile
router.include_router(chat)  # /api/chat/* conversations, message streams, and run state

# Management and workspace interfaces: background tasks, permissions, and tools.
router.include_router(dashboard)  # /api/dashboard/* dashboard aggregate data
router.include_router(department)  # /api/departments/* department and permission data
router.include_router(tasks)  # /api/tasks/* background task query and management
router.include_router(mcp)  # /api/system/mcp-servers/* MCP servicemanagement
router.include_router(skills)  # /api/system/skills/* Skills management
router.include_router(subagents_router)  # /api/system/subagents/* sub-agent management
router.include_router(tools)  # /api/system/tools/* tool list and configuration
router.include_router(apikey_router)  # /api/apikey/* API Key management

if not _LITE_MODE:
    from server.routers.graph_router import graph
    from server.routers.knowledge_router import knowledge
    from server.routers.evaluation_router import evaluation
    from server.routers.mindmap_router import mindmap

    # Knowledge base and graph dependencies are heavy, so LITE mode skips them.
    router.include_router(knowledge)  # /api/knowledge/* knowledge base management and retrieval
    router.include_router(evaluation)  # /api/evaluation/* knowledge baseevaluation
    router.include_router(mindmap)  # /api/mindmap/* mind map generation and query
    router.include_router(graph)  # /api/graph/* graph query and management
