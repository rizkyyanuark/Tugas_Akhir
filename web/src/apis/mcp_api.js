import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

/**
 * MCP server management API module
 * Includes CRUD operations for MCP servers and tool management features
 */

const BASE_URL = '/api/system/mcp-servers'

// =============================================================================
// === MCP server CRUD ===
// =============================================================================

/**
 * Get all MCP server configurations
 * @returns {Promise} - Server list
 */
export const getMcpServers = async () => {
  return apiAdminGet(BASE_URL)
}

/**
 * Get a single MCP server configuration
 * @param {string} name - Server name
 * @returns {Promise} - Server configuration
 */
export const getMcpServer = async (name) => {
  return apiAdminGet(`${BASE_URL}/${encodeURIComponent(name)}`)
}

/**
 * Create a new MCP server
 * @param {Object} data - Server configuration data
 * @returns {Promise} - Creation result
 */
export const createMcpServer = async (data) => {
  return apiAdminPost(BASE_URL, data)
}

/**
 * Update an MCP server configuration
 * @param {string} name - Server name
 * @param {Object} data - Updated data
 * @returns {Promise} - Update result
 */
export const updateMcpServer = async (name, data) => {
  return apiAdminPut(`${BASE_URL}/${encodeURIComponent(name)}`, data)
}

/**
 * Delete an MCP server
 * @param {string} name - Server name
 * @returns {Promise} - Deletion result
 */
export const deleteMcpServer = async (name) => {
  return apiAdminDelete(`${BASE_URL}/${encodeURIComponent(name)}`)
}

// =============================================================================
// === MCP server operations ===
// =============================================================================

/**
 * Test an MCP server connection
 * @param {string} name - Server name
 * @returns {Promise} - Test result
 */
export const testMcpServer = async (name) => {
  return apiAdminPost(`${BASE_URL}/${encodeURIComponent(name)}/test`, {})
}

/**
 * Update an MCP server enabled status
 * @param {string} name - Server name
 * @param {boolean} enabled - Whether enabled
 * @returns {Promise} - Toggle result
 */
export const updateMcpServerStatus = async (name, enabled) => {
  return apiAdminPut(`${BASE_URL}/${encodeURIComponent(name)}/status`, { enabled })
}

// =============================================================================
// === MCP tool management ===
// =============================================================================

/**
 * Get the tool list for an MCP server
 * @param {string} name - Server name
 * @returns {Promise} - Tool list
 */
export const getMcpServerTools = async (name) => {
  return apiAdminGet(`${BASE_URL}/${encodeURIComponent(name)}/tools`)
}

/**
 * Refresh the tool list for an MCP server (clear cache and fetch again)
 * @param {string} name - Server name
 * @returns {Promise} - Refresh result
 */
export const refreshMcpServerTools = async (name) => {
  return apiAdminPost(`${BASE_URL}/${encodeURIComponent(name)}/tools/refresh`, {})
}

/**
 * Toggle a single tool's enabled state
 * @param {string} serverName - Server name
 * @param {string} toolName - Tool name
 * @returns {Promise} - Toggle result
 */
export const toggleMcpServerTool = async (serverName, toolName) => {
  return apiAdminPut(
    `${BASE_URL}/${encodeURIComponent(serverName)}/tools/${encodeURIComponent(toolName)}/toggle`,
    {}
  )
}

// =============================================================================
// === Export as an object (compatible with the existing code style) ===
// =============================================================================

export const mcpApi = {
  getMcpServers,
  getMcpServer,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  testMcpServer,
  updateMcpServerStatus,
  getMcpServerTools,
  refreshMcpServerTools,
  toggleMcpServerTool
}

export default mcpApi
