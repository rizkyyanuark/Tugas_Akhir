import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

/**
 * SubAgent management API module
 * Includes CRUD operations for SubAgent records
 */

const BASE_URL = '/api/system/subagents'

// =============================================================================
// === SubAgent CRUD ===
// =============================================================================

/**
 * Get all SubAgent configurations
 * @returns {Promise} - SubAgent list
 */
export const getSubAgents = async () => {
  return apiAdminGet(BASE_URL)
}

/**
 * Get a single SubAgent configuration
 * @param {string} name - SubAgent name
 * @returns {Promise} - SubAgent configuration
 */
export const getSubAgent = async (name) => {
  return apiAdminGet(`${BASE_URL}/${encodeURIComponent(name)}`)
}

/**
 * Create a new SubAgent
 * @param {Object} data - SubAgent configuration data
 * @returns {Promise} - Creation result
 */
export const createSubAgent = async (data) => {
  return apiAdminPost(BASE_URL, data)
}

/**
 * Update a SubAgent configuration
 * @param {string} name - SubAgent name
 * @param {Object} data - Update data
 * @returns {Promise} - Update result
 */
export const updateSubAgent = async (name, data) => {
  return apiAdminPut(`${BASE_URL}/${encodeURIComponent(name)}`, data)
}

/**
 * Delete a SubAgent
 * @param {string} name - SubAgent name
 * @returns {Promise} - Deletion result
 */
export const deleteSubAgent = async (name) => {
  return apiAdminDelete(`${BASE_URL}/${encodeURIComponent(name)}`)
}

export const updateSubAgentStatus = async (name, enabled) => {
  return apiAdminPut(`${BASE_URL}/${encodeURIComponent(name)}/status`, { enabled })
}

// =============================================================================
// === Export as object form (compatible with existing code style) ===
// =============================================================================

export const subagentApi = {
  getSubAgents,
  getSubAgent,
  createSubAgent,
  updateSubAgent,
  deleteSubAgent,
  updateSubAgentStatus
}

export default subagentApi
