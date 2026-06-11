import { apiAdminGet } from './base'

/**
 * Dashboard API module
 * Used by administrators to view conversation records for all users
 */

export const dashboardApi = {
  /**
   * Get all conversation records
   * @param {Object} params - Query parameters
   * @param {string} params.user_id - Filter by user ID
   * @param {string} params.agent_id - Filter by agent ID
   * @param {string} params.status - Status filter (active/deleted/all)
   * @param {number} params.limit - Items per page
   * @param {number} params.offset - Offset
   * @returns {Promise<Array>} - Conversation list
   */
  getConversations: (params = {}) => {
    const queryParams = new URLSearchParams()
    if (params.user_id) queryParams.append('user_id', params.user_id)
    if (params.agent_id) queryParams.append('agent_id', params.agent_id)
    if (params.status) queryParams.append('status', params.status)
    if (params.limit) queryParams.append('limit', params.limit)
    if (params.offset) queryParams.append('offset', params.offset)

    return apiAdminGet(`/api/dashboard/conversations?${queryParams.toString()}`)
  },

  /**
   * Get conversation details
   * @param {string} threadId - Conversation thread ID
   * @returns {Promise<Object>} - Conversation details
   */
  getConversationDetail: (threadId) => {
    return apiAdminGet(`/api/dashboard/conversations/${threadId}`)
  },

  /**
   * Get dashboard statistics
   * @returns {Promise<Object>} - Statistics
   */
  getStats: () => {
    return apiAdminGet('/api/dashboard/stats')
  },

  /**
   * Get the feedback list
   * @param {Object} params - Query parameters
   * @param {string} params.rating - Feedback filter (like/dislike/all)
   * @param {string} params.agent_id - Filter by agent ID
   * @returns {Promise<Array>} - Feedback list
   */
  getFeedbacks: (params = {}) => {
    const queryParams = new URLSearchParams()
    if (params.rating && params.rating !== 'all') queryParams.append('rating', params.rating)
    if (params.agent_id) queryParams.append('agent_id', params.agent_id)

    return apiAdminGet(`/api/dashboard/feedbacks?${queryParams.toString()}`)
  },

  // ========== Newly added parallel API endpoints ==========

  /**
   * Get user activity statistics
   * @returns {Promise<Object>} - User activity statistics
   */
  getUserStats: () => {
    return apiAdminGet('/api/dashboard/stats/users')
  },

  /**
   * Get tool invocation statistics
   * @returns {Promise<Object>} - Tool invocation statistics
   */
  getToolStats: () => {
    return apiAdminGet('/api/dashboard/stats/tools')
  },

  /**
   * Get knowledge base statistics
   * @returns {Promise<Object>} - Knowledge base statistics
   */
  getKnowledgeStats: () => {
    return apiAdminGet('/api/dashboard/stats/knowledge')
  },

  /**
   * Get AI agent analysis data
   * @returns {Promise<Object>} - AI agent analysis data
   */
  getAgentStats: () => {
    return apiAdminGet('/api/dashboard/stats/agents')
  },

  /**
   * Fetch all statistics in parallel
   * @returns {Promise<Object>} - All statistics
   */
  getAllStats: async () => {
    const requests = {
      basic: apiAdminGet('/api/dashboard/stats'),
      users: apiAdminGet('/api/dashboard/stats/users'),
      tools: apiAdminGet('/api/dashboard/stats/tools'),
      knowledge: apiAdminGet('/api/dashboard/stats/knowledge'),
      agents: apiAdminGet('/api/dashboard/stats/agents'),
      academic: apiAdminGet('/api/dashboard/stats/academic')
    }

    const keys = Object.keys(requests)
    const results = await Promise.allSettled(Object.values(requests))
    const response = { failures: [] }

    results.forEach((result, index) => {
      const key = keys[index]
      if (result.status === 'fulfilled') {
        response[key] = result.value
      } else {
        response[key] = null
        response.failures.push(key)
        console.error(`Failed to fetch dashboard source "${key}":`, result.reason)
      }
    })

    if (!response.basic) {
      throw new Error('Basic dashboard statistics are unavailable.')
    }
    return response
  },

  /**
   * Get call timeseries data
   * @param {string} type - Data type (models/agents/tokens/tools)
   * @param {string} timeRange - Time range (14hours/14days/14weeks)
   * @returns {Promise<Object>} - Timeseries statistics
   */
  getCallTimeseries: (type = 'models', timeRange = '14days') => {
    return apiAdminGet(`/api/dashboard/stats/calls/timeseries?type=${type}&time_range=${timeRange}`)
  },

  /**
   * Get academic statistics (paper count, lecturer count, KG nodes)
   * Used by DashboardView for UNESA academic metrics
   * @returns {Promise<Object>} - Academic corpus, graph, vector, and source health metrics.
   */
  getAcademicStats: () => {
    return apiAdminGet('/api/dashboard/stats/academic')
  }
}
