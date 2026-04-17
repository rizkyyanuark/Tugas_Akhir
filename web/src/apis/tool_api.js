import { apiAdminGet } from './base'

/**
 * Tool management API module
 * Provides query functionality for system built-in tools
 */

const BASE_URL = '/api/system/tools'

/**
 * Get the tool list
 * @param {string} category - Optional category filter
 * @returns {Promise} - Tool list
 */
export const getTools = async (category = null) => {
  const params = category ? { category } : {}
  return apiAdminGet(BASE_URL, params)
}

/**
 * Get the tool options list (for dropdown selection)
 * @returns {Promise} - Tool options
 */
export const getToolOptions = async () => {
  return apiAdminGet(`${BASE_URL}/options`)
}

// =============================================================================
// === Export as an object (compatible with the existing code style) ===
// =============================================================================

export const toolApi = {
  getTools,
  getToolOptions
}

export default toolApi
