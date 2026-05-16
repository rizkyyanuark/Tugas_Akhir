import {
  apiGet,
  apiPost,
  apiDelete,
  apiPut,
  apiAdminPost,
  apiAdminDelete
} from './base'
import { useUserStore } from '@/stores/user'

/**
 * Agent API module
 * Includes agent management, chat, configuration, and more
 * Permission required: any authenticated user (regular user, admin, super admin)
 */

// =============================================================================
// === Agent chat group ===
// =============================================================================

export const agentApi = {
  /**
   * Send a chat message to the specified agent (streaming response)
   * @param {Object} data - Chat payload
   * @returns {Promise} - Chat response stream
   */
  sendAgentMessage: (data, options = {}) => {
    const { signal, headers: extraHeaders, ...restOptions } = options || {}
    const baseHeaders = {
      'Content-Type': 'application/json',
      ...useUserStore().getAuthHeaders()
    }

    return fetch('/api/chat/agent', {
      method: 'POST',
      body: JSON.stringify(data),
      signal,
      headers: {
        ...baseHeaders,
        ...(extraHeaders || {})
      },
      ...restOptions
    })
  },

  /**
   * Simple chat call (non-streaming)
   * @param {string} query - Query content
   * @returns {Promise} - Chat response
   */
  simpleCall: (query) => apiPost('/api/chat/call', { query }),

  /**
   * Generate a conversation title
   * @param {string} query - Query content
   * @param {Object} modelSpec - Model configuration
   * @returns {Promise<string>} - Generated title
   */
  generateTitle: async (query, modelSpec) => {
    const response = await apiPost('/api/chat/call', {
      query: `Generate a short title from the following conversation content (up to 30 characters, Chinese or English is fine). Do not include markdown syntax:\n\n${query.slice(0, 2000)}`,
      meta: { model_spec: modelSpec }
    })
    return response.response
  },

  /**
   * Get the default agent
   * @returns {Promise} - Default agent information
   */
  getDefaultAgent: () => apiGet('/api/chat/default_agent'),

  /**
   * Get the agent list
   * @returns {Promise} - Agent list
   */
  getAgents: () => apiGet('/api/chat/agent'),

  /**
   * Get details for a single agent
   * @param {string} agentId - Agent ID
   * @returns {Promise} - Agent details
   */
  getAgentDetail: (agentId) => apiGet(`/api/chat/agent/${agentId}`),

  /**
   * Get an agent's history messages
   * @param {string} agentId - Agent ID
   * @param {string} threadId - Thread ID
   * @returns {Promise} - History messages
   */
  getAgentHistory: (threadId) => apiGet(`/api/chat/thread/${threadId}/history`),

  /**
   * Get the AgentState for a specified thread
   * @param {string} agentId - Agent ID
   * @param {string} threadId - Thread ID
   * @returns {Promise} - AgentState
   */
  getAgentState: (threadId) => apiGet(`/api/chat/thread/${threadId}/state`),

  /**
   * Submit feedback for a message
   * @param {number} messageId - Message ID
   * @param {string} rating - 'like' or 'dislike'
   * @param {string|null} reason - Optional reason for dislike
   * @returns {Promise} - Feedback response
   */
  submitMessageFeedback: (messageId, rating, reason = null) =>
    apiPost(`/api/chat/message/${messageId}/feedback`, { rating, reason }),

  /**
   * Get feedback status for a message
   * @param {number} messageId - Message ID
   * @returns {Promise} - Feedback status
   */
  getMessageFeedback: (messageId) => apiGet(`/api/chat/message/${messageId}/feedback`),

  /**
   * Get the model list for a model provider
   * @param {string} provider - Model provider
   * @returns {Promise} - Model list
   */
  getProviderModels: (provider) => apiGet(`/api/chat/models?model_provider=${provider}`),

  /**
   * Update the model list for a model provider
   * @param {string} provider - Model provider
   * @param {Array} models - Selected model list
   * @returns {Promise} - Update result
   */
  updateProviderModels: (provider, models) =>
    apiPost(`/api/chat/models/update?model_provider=${provider}`, models),

  getAgentConfigs: (agentId) => apiGet(`/api/chat/agent/${agentId}/configs`),

  getAgentConfigProfile: (agentId, configId) =>
    apiGet(`/api/chat/agent/${agentId}/configs/${configId}`),

  createAgentConfigProfile: (agentId, payload) =>
    apiAdminPost(`/api/chat/agent/${agentId}/configs`, payload),

  updateAgentConfigProfile: (agentId, configId, payload) =>
    apiPut(`/api/chat/agent/${agentId}/configs/${configId}`, payload),

  setAgentConfigDefault: (agentId, configId) =>
    apiAdminPost(`/api/chat/agent/${agentId}/configs/${configId}/set_default`, {}),

  deleteAgentConfigProfile: (agentId, configId) =>
    apiAdminDelete(`/api/chat/agent/${agentId}/configs/${configId}`),

  /**
   * Set the default agent
   * @param {string} agentId - Agent ID
   * @returns {Promise} - Update result
   */
  setDefaultAgent: async (agentId) => {
    return apiAdminPost('/api/chat/set_default_agent', { agent_id: agentId })
  },

  /**
   * Resume a conversation interrupted by manual approval (streaming response)
   * @param {string} agentId - Agent ID
   * @param {Object} data - Resume payload { thread_id, answer: { question_id: answer }, approved }
   * @param {Object} options - Optional parameters (signal, headers, etc.)
   * @returns {Promise} - Resume response stream
   */
  resumeAgentChat: (threadId, data, options = {}) => {
    const { signal, headers: extraHeaders, ...restOptions } = options || {}
    const baseHeaders = {
      'Content-Type': 'application/json',
      ...useUserStore().getAuthHeaders()
    }

    return fetch(`/api/chat/thread/${threadId}/resume`, {
      method: 'POST',
      body: JSON.stringify(data),
      signal,
      headers: {
        ...baseHeaders,
        ...(extraHeaders || {})
      },
      ...restOptions
    })
  },

  /**
   * Create an asynchronous run task
   * @param {Object} data - Run request body
   * @returns {Promise<Object>}
   */
  createAgentRun: (data) =>
    apiPost('/api/chat/runs', {
      query: data.query,
      agent_config_id: data.agent_config_id,
      thread_id: data.thread_id,
      meta: data.meta || {}
    }),

  /**
   * Get run status
   * @param {string} runId - Run ID
   * @returns {Promise<Object>}
   */
  getAgentRun: (runId) => apiGet(`/api/chat/runs/${runId}`),

  /**
   * Cancel a run
   * @param {string} runId - Run ID
   * @returns {Promise<Object>}
   */
  cancelAgentRun: (runId) => apiPost(`/api/chat/runs/${runId}/cancel`, {}),

  /**
   * Get the active run for a thread
   * @param {string} threadId - Thread ID
   * @returns {Promise<Object>}
   */
  getThreadActiveRun: (threadId) => apiGet(`/api/chat/thread/${threadId}/active_run`),

  /**
   * Open a Run event SSE connection (caller is responsible for closing it)
   * @param {string} runId - Run ID
   * @param {string|number} afterSeq - Starting seq/cursor
   * @param {Object} options - { signal }
   * @returns {Promise<Response>}
   */
  streamAgentRunEvents: (runId, afterSeq = '0', options = {}) => {
    const { signal } = options
    return fetch(
      `/api/chat/runs/${runId}/events?after_seq=${encodeURIComponent(String(afterSeq))}`,
      {
        method: 'GET',
        headers: {
          ...useUserStore().getAuthHeaders()
        },
        signal
      }
    )
  }
}

// =============================================================================
// === Conversation thread group ===
// =============================================================================

export const threadApi = {
  /**
   * Get the conversation thread list
   * @param {string | null | undefined} agentId - Agent ID, optional; returns all agent conversations when omitted
   * @param {number} limit - Result limit, default 100
   * @param {number} offset - Offset, default 0
   * @returns {Promise} - Conversation thread list
   */
  getThreads: (agentId = null, limit = 100, offset = 0) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset)
    })
    if (agentId) {
      params.set('agent_id', agentId)
    }
    const url = `/api/chat/threads?${params.toString()}`
    return apiGet(url)
  },

  /**
   * Create a new conversation thread
   * @param {string} agentId - Agent ID
   * @param {string} title - Conversation title
   * @param {Object} metadata - Metadata
   * @returns {Promise} - Creation result
   */
  createThread: (agentId, title, metadata) =>
    apiPost('/api/chat/thread', {
      agent_id: agentId,
      title: title || 'New Conversation',
      metadata: metadata || {}
    }),

  /**
   * Update a conversation thread
   * @param {string} threadId - Conversation thread ID
   * @param {string} title - Conversation title
   * @param {boolean} is_pinned - Whether pinned
   * @returns {Promise} - Update result
   */
  updateThread: (threadId, title, is_pinned) =>
    apiPut(`/api/chat/thread/${threadId}`, {
      title,
      is_pinned
    }),

  /**
   * Delete a conversation thread
   * @param {string} threadId - Conversation thread ID
   * @returns {Promise} - Deletion result
   */
  deleteThread: (threadId) => apiDelete(`/api/chat/thread/${threadId}`),

  /**
   * File-system and attachment APIs were intentionally removed from the chat UI.
   * The project scope is text-only question answering over graph/vector context.
   */
}
