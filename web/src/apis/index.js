/**
 * API module index file
 * Exports all API modules for convenient unified imports
 */

// Export API modules
export * from './system_api' // System management API
export * from './knowledge_api' // Knowledge base management API
export * from './graph_api' // Graph API
export * from './agent_api' // Agent API
export * from './tasker' // Task management API
export * from './mindmap_api' // Mind map API
export * from './department_api' // Department management API
export * from './mcp_api' // MCP API
export * from './skill_api' // Skills API
export * from './subagent_api' // SubAgent API
export * from './tool_api' // Tool API

// Export base utility functions
export {
  apiGet,
  apiPost,
  apiPut,
  apiDelete,
  apiAdminGet,
  apiAdminPost,
  apiAdminPut,
  apiAdminDelete,
  apiSuperAdminGet,
  apiSuperAdminPost,
  apiSuperAdminPut,
  apiSuperAdminDelete
} from './base'

/**
 * API module notes:
 *
 * 1. system_api.js: System management API
 *    - Health checks, configuration management, information management, OCR service
 *    - Permissions: partly public, partly admin-only
 *
 * 2. knowledge_api.js: Knowledge base management API
 *    - Database management, document management, query interface, file management
 *    - Permissions: admin only
 *
 * 4. graph_api.js: Graph API
 *    - Knowledge graph related features
 *
 * 5. tools.js: Tool API
 *    - Tool information retrieval
 *
 * 6. agent.js: Agent API
 *    - Agent management, chat, configuration, and more
 *
 * Note: API modules already handle permission checks and request headers, so you do not need to add auth headers manually.
 */
