import { apiAdminGet, apiAdminPost } from './base'

/**
 * Mind map API module
 * Provides endpoints related to mind map generation
 */

// =============================================================================
// === Knowledge base management ===
// =============================================================================

export const mindmapApi = {
  /**
  * Get an overview list of all knowledge bases for selection
  * @returns {Promise} - Knowledge base list
   */
  getDatabases: async () => {
    return apiAdminGet('/api/mindmap/databases')
  },

  /**
  * Get the file list for a specific knowledge base
  * @param {string} dbId - Knowledge base ID
  * @returns {Promise} - File list
   */
  getDatabaseFiles: async (dbId) => {
    return apiAdminGet(`/api/mindmap/databases/${dbId}/files`)
  },

  /**
  * Generate a mind map with AI
  * @param {string} dbId - Knowledge base ID
  * @param {Array<string>} fileIds - Selected file IDs (uses all files when empty)
  * @param {string} userPrompt - User-defined prompt
  * @returns {Promise} - Mind map data
   */
  generateMindmap: async (dbId, fileIds = [], userPrompt = '') => {
    return apiAdminPost('/api/mindmap/generate', {
      db_id: dbId,
      file_ids: fileIds,
      user_prompt: userPrompt
    })
  },

  /**
  * Get the mind map for a knowledge base
  * @param {string} dbId - Knowledge base ID
  * @returns {Promise} - Mind map data
   */
  getByDatabase: async (dbId) => {
    return apiAdminGet(`/api/mindmap/database/${dbId}`)
  }
}
