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
from server.routers.filesystem_router import filesystem_router

_LITE_MODE = os.environ.get("LITE_MODE", "").lower() in ("true", "1")

router = APIRouter()

# 基础systeminterface：健康check、configure、authentication与聊天主链路。
router.include_router(system)  # /api/system/* systemstatus与全局configure
router.include_router(auth)  # /api/auth/* login与user信息
router.include_router(chat)  # /api/chat/* conversation、message流、运row态

# management与工作台interface：后台task、permission域以及tool体系configure。
router.include_router(dashboard)  # /api/dashboard/* 仪table盘聚合data
router.include_router(department)  # /api/departments/* department与permissionrelateddata
router.include_router(tasks)  # /api/tasks/* 后台taskquery与management
router.include_router(mcp)  # /api/system/mcp-servers/* MCP servicemanagement
router.include_router(skills)  # /api/system/skills/* Skills management
router.include_router(subagents_router)  # /api/system/subagents/* 子agentmanagement
router.include_router(tools)  # /api/system/tools/* toollist与configure
router.include_router(apikey_router)  # /api/apikey/* API Key management
router.include_router(filesystem_router)  # /api/viewer/filesystem/* 工作台filesystem视图

if not _LITE_MODE:
    from server.routers.graph_router import graph
    from server.routers.knowledge_router import knowledge
    from server.routers.evaluation_router import evaluation
    from server.routers.mindmap_router import mindmap

    # knowledge base与graph能力dependency较重，LITE 模式下跳过这组interface。
    router.include_router(knowledge)  # /api/knowledge/* knowledge basemanagement与retrieval
    router.include_router(evaluation)  # /api/evaluation/* knowledge baseevaluation
    router.include_router(mindmap)  # /api/mindmap/* 思维导图generate与query
    router.include_router(graph)  # /api/graph/* graphquery与management
