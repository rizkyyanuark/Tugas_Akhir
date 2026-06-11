import { message } from 'ant-design-vue'

/**
 * Unified error handling utility class
 */
export class ErrorHandler {
  static getFriendlyErrorMessage(rawMessage, context = 'Operation') {
    const text = String(rawMessage || '').trim()
    if (!text) return `${context} failed`

    const lower = text.toLowerCase()

    if (
      lower.includes('model does not exist') ||
      lower.includes('badrequesterror') ||
      lower.includes('not registered for this provider') ||
      lower.includes('selected model') ||
      lower.includes('provider') && lower.includes('not configured')
    ) {
      return 'The selected AI provider or model is not available. Choose an available model in Settings, then try again.'
    }

    if (
      lower.includes('authentication failed') ||
      lower.includes('invalid api key') ||
      lower.includes('api key') && (lower.includes('missing') || lower.includes('invalid'))
    ) {
      return 'The AI provider API key is missing or invalid. Check the provider configuration, then try again.'
    }

    if (lower.includes('rate limit') || lower.includes('too many requests')) {
      return 'The AI provider is rate-limiting requests. Wait a moment, then try again.'
    }

    if (lower.includes('timeout') || lower.includes('network') || lower.includes('connection')) {
      return 'The AI provider could not be reached. Check the service connection, then try again.'
    }

    return `${context} failed: ${text}`
  }

  /**
   * Handles generic errors
   * @param {Error} error - Error object
   * @param {string} context - Error context
   * @param {Object} options - Configuration options
   */
  static handleError(error, context = 'Operation', options = {}) {
    const {
      showMessage = true,
      logToConsole = true,
      customMessage = null,
      severity = 'error'
    } = options

    // Console logging
    if (logToConsole) {
      console.error(`${context} failed:`, error)
    }

    // User notification
    if (showMessage) {
      const displayMessage = customMessage || this.getErrorMessage(error, context)

      switch (severity) {
        case 'warning':
          message.warning(displayMessage)
          break
        case 'info':
          message.info(displayMessage)
          break
        case 'error':
        default:
          message.error(displayMessage)
          break
      }
    }

    return error
  }

  /**
   * Gets error message
   * @param {Error} error - Error object
   * @param {string} context - Error context
   * @returns {string} Error message
   */
  static getErrorMessage(error, context) {
    if (error?.message) {
      return this.getFriendlyErrorMessage(error.message, context)
    }
    return `${context} failed`
  }

  /**
   * Handles network request errors
   * @param {Error} error - Error object
   * @param {string} context - Error context
   */
  static handleNetworkError(error, context = 'Network Request') {
    let customMessage = null

    if (error?.code === 'NETWORK_ERROR') {
      customMessage = 'Network connection failed, please check your settings'
    } else if (error?.status === 401) {
      customMessage = 'Authentication failed, please login again'
    } else if (error?.status === 403) {
      customMessage = 'Insufficient permissions'
    } else if (error?.status === 404) {
      customMessage = 'Requested resource not found'
    } else if (error?.status >= 500) {
      customMessage = 'Server error, please try again later'
    }

    return this.handleError(error, context, { customMessage })
  }

  /**
   * Handles chat related errors
   * @param {Error} error - Error object
   * @param {string} operation - Operation type
   */
  static handleChatError(error, operation) {
    const contextMap = {
      send: 'Sending message',
      create: 'Creating conversation',
      delete: 'Deleting conversation',
      rename: 'Renaming conversation',
      load: 'Loading conversation',
      export: 'Exporting conversation',
      stream: 'Streaming'
    }

    const context = contextMap[operation] || operation
    return this.handleError(error, context)
  }

  /**
   * Handles validation errors
   * @param {string} message - Validation error message
   */
  static handleValidationError(message) {
    return this.handleError(new Error(message), 'Validation', {
      severity: 'warning',
      customMessage: message
    })
  }

  /**
   * Handles asynchronous operation errors
   * @param {Function} asyncFn - Async function
   * @param {string} context - Error context
   * @param {Object} options - Configuration options
   */
  static async handleAsync(asyncFn, context, options = {}) {
    try {
      return await asyncFn()
    } catch (error) {
      this.handleError(error, context, options)
      throw error
    }
  }

  /**
   * Creates an error handling decorator/wrapper
   * @param {string} context - Error context
   * @param {Object} options - Configuration options
   */
  static createHandler(context, options = {}) {
    return (error) => this.handleError(error, context, options)
  }
}

/**
 * Shorthand methods
 */
export const handleChatError = ErrorHandler.handleChatError.bind(ErrorHandler)
export const handleNetworkError = ErrorHandler.handleNetworkError.bind(ErrorHandler)
export const handleValidationError = ErrorHandler.handleValidationError.bind(ErrorHandler)
export const handleAsync = ErrorHandler.handleAsync.bind(ErrorHandler)

export default ErrorHandler
