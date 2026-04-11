import { message } from 'ant-design-vue'

/**
 * Unified error handling utility class
 */
export class ErrorHandler {
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
      return `${context} failed: ${error.message}`
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
