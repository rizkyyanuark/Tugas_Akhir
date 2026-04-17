import { apiGet, apiPost, apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

/**
 * System management API module
 * Includes system configuration, health checks, information management, and related features
 */

// =============================================================================
// === Health check group ===
// =============================================================================

export const healthApi = {
  /**
   * System health check (public endpoint)
   * @returns {Promise} - Health check result
   */
  checkHealth: () => apiGet('/api/system/health', {}, false),

  /**
   * OCR service health check
   * @returns {Promise} - OCR service health status
   */
  checkOcrHealth: async () => apiAdminGet('/api/system/health/ocr')
}

// =============================================================================
// === Configuration management group ===
// =============================================================================

export const configApi = {
  /**
   * Get system configuration
   * @returns {Promise} - System configuration
   */
  getConfig: async () => apiAdminGet('/api/system/config'),

  /**
   * Update a single configuration item
   * @param {string} key - Configuration key
   * @param {any} value - Configuration value
   * @returns {Promise} - Update result
   */
  updateConfig: async (key, value) => apiAdminPost('/api/system/config', { key, value }),

  /**
   * Update configuration items in bulk
   * @param {Object} items - Configuration item object
   * @returns {Promise} - Update result
   */
  updateConfigBatch: async (items) => apiAdminPost('/api/system/config/update', items),

  /**
   * Get system logs
   * @param {string} levels - Optional log level filter, comma-separated
   * @returns {Promise} - System logs
   */
  getLogs: async (levels) => {
    const url = levels
      ? `/api/system/logs?levels=${encodeURIComponent(levels)}`
      : '/api/system/logs'
    return apiAdminGet(url)
  }
}

// =============================================================================
// === Information management group ===
// =============================================================================

export const brandApi = {
  /**
   * Get system information configuration (public endpoint)
   * @returns {Promise} - System information configuration
   */
  getInfoConfig: () => apiGet('/api/system/info', {}, false),

  /**
   * Reload the information configuration
   * @returns {Promise} - Reload result
   */
  reloadInfoConfig: async () => apiPost('/api/system/info/reload', {}, {}, false)
}

// =============================================================================
// === OCR service group ===
// =============================================================================

export const ocrApi = {
  /**
   * Get OCR service health status
   * @returns {Promise} - OCR health status
   */
  getHealth: async () => apiAdminGet('/api/system/ocr/health')
}

// =============================================================================
// === Chat model status check group ===
// =============================================================================

export const chatModelApi = {
  /**
   * Get the status of a specific chat model
   * @param {string} provider - Model provider
   * @param {string} modelName - Model name
   * @returns {Promise} - Model status
   */
  getModelStatus: async (provider, modelName) => {
    return apiAdminGet(
      `/api/system/chat-models/status?provider=${encodeURIComponent(provider)}&model_name=${encodeURIComponent(modelName)}`
    )
  },

  /**
   * Get the status of all chat models
   * @returns {Promise} - All model statuses
   */
  getAllModelsStatus: async () => {
    return apiAdminGet('/api/system/chat-models/all/status')
  }
}

// =============================================================================
// === Custom provider management group ===
// =============================================================================

export const customProviderApi = {
  /**
   * Get all custom providers
   * @returns {Promise} - Custom provider list
   */
  getCustomProviders: async () => {
    return apiAdminGet('/api/system/custom-providers')
  },

  /**
   * Add a custom provider
   * @param {string} providerId - Provider ID
   * @param {Object} providerData - Provider configuration data
   * @returns {Promise} - Add result
   */
  addCustomProvider: async (providerId, providerData) => {
    return apiAdminPost('/api/system/custom-providers', {
      provider_id: providerId,
      provider_data: providerData
    })
  },

  /**
   * Update a custom provider
   * @param {string} providerId - Provider ID
   * @param {Object} providerData - Provider configuration data
   * @returns {Promise} - Update result
   */
  updateCustomProvider: async (providerId, providerData) => {
    return apiAdminPut(
      `/api/system/custom-providers/${encodeURIComponent(providerId)}`,
      providerData
    )
  },

  /**
   * Delete a custom provider
   * @param {string} providerId - Provider ID
   * @returns {Promise} - Deletion result
   */
  deleteCustomProvider: async (providerId) => {
    return apiAdminDelete(`/api/system/custom-providers/${encodeURIComponent(providerId)}`)
  },

  /**
   * Test a custom provider connection
   * @param {string} providerId - Provider ID
   * @param {string} modelName - Model name to test
   * @returns {Promise} - Test result
   */
  testCustomProvider: async (providerId, modelName) => {
    return apiAdminPost(`/api/system/custom-providers/${encodeURIComponent(providerId)}/test`, {
      model_name: modelName
    })
  }
}
