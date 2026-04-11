/**
 * Agent ID validation utility class
 * Centralized validation logic for Agent ID-related operations
 */
export class AgentValidator {
  /**
   * Validate whether an Agent ID exists
   * @param {string} agentId - Agent ID to validate
   * @param {string} operation - Operation name used in error messages
   * @returns {boolean} Whether validation passed
   */
  static validateAgentId(agentId, operation = 'operation') {
    if (!agentId) {
      console.warn(`No Agent ID was specified, cannot ${operation}`)
      return false
    }
    return true
  }

  /**
   * Validate an Agent ID and display an error message
   * @param {string} agentId - Agent ID to validate
   * @param {string} operation - Operation name
   * @param {Function} errorHandler - Error handler
   * @returns {boolean} Whether validation passed
   */
  static validateAgentIdWithError(agentId, operation, errorHandler) {
    if (!agentId) {
      const message = `No Agent ID was specified, cannot ${operation}`
      if (errorHandler) {
        errorHandler(message)
      }
      return false
    }
    return true
  }

  /**
   * Validate prerequisites for chat-related operations
   * @param {string} agentId - Agent ID
   * @param {string} chatId - Conversation ID (optional)
   * @param {string} operation - Operation name
   * @param {Function} errorHandler - Error handler
   * @returns {boolean} Whether validation passed
   */
  static validateChatOperation(agentId, chatId, operation, errorHandler) {
    // Validate Agent ID
    if (!this.validateAgentIdWithError(agentId, operation, errorHandler)) {
      return false
    }

    // If chatId validation is required
    if (chatId !== undefined && !chatId) {
      const message = 'Please select a conversation first'
      if (errorHandler) {
        errorHandler(message)
      }
      return false
    }

    return true
  }

  /**
   * Validate parameters for rename operations
   * @param {string} chatId - Conversation ID
   * @param {string} title - New title
   * @param {string} agentId - Agent ID
   * @param {Function} errorHandler - Error handler
   * @returns {boolean} Whether validation passed
   */
  static validateRenameOperation(chatId, title, agentId, errorHandler) {
    // Validate basic parameters
    if (!chatId || !title) {
      const message = 'No conversation ID or title was specified; cannot rename the conversation'
      if (errorHandler) {
        errorHandler(message)
      }
      return false
    }

    // Ensure the title is not empty
    if (!title.trim()) {
      const message = 'Title cannot be empty'
      if (errorHandler) {
        errorHandler(message)
      }
      return false
    }

    // Validate Agent ID
    return this.validateAgentIdWithError(agentId, 'rename the conversation', errorHandler)
  }

  /**
   * Validate prerequisites for share operations
   * @param {string} chatId - Conversation ID
   * @param {Object} agent - Current agent object
   * @param {Function} errorHandler - Error handler
   * @returns {boolean} Whether validation passed
   */
  static validateShareOperation(chatId, agent, errorHandler) {
    if (!chatId || !agent) {
      const message = 'Please select a conversation first'
      if (errorHandler) {
        errorHandler(message)
      }
      return false
    }
    return true
  }

  /**
   * Validate prerequisites for load operations
   * @param {string} agentId - Agent ID
   * @param {string} operation - Operation name
   * @returns {boolean} Whether validation passed
   */
  static validateLoadOperation(agentId, operation = 'load state') {
    if (!agentId) {
      console.warn(`No Agent ID was specified, cannot ${operation}`)
      return false
    }
    return true
  }
}
