import { useUserStore, checkAdminPermission, checkSuperAdminPermission } from '@/stores/user'
import { message } from 'ant-design-vue'

/**
 * Base API request wrapper
 * Provides a unified request method that automatically handles auth headers and errors
 */

/**
 * Base function for sending API requests
 * @param {string} url - API endpoint
 * @param {Object} options - Request options
 * @param {boolean} requiresAuth - Whether an auth header is required
 * @param {string} responseType - Response type: 'json' | 'text' | 'blob'
 * @returns {Promise} - Request result
 */
export async function apiRequest(url, options = {}, requiresAuth = true, responseType = 'json') {
  try {
    const isFormData = options?.body instanceof FormData
    // Default request options
    const requestOptions = {
      ...options,
      headers: {
        ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers
      }
    }

    // Add auth headers if required
    if (requiresAuth) {
      const userStore = useUserStore()
      if (!userStore.isLoggedIn) {
        throw new Error('User is not logged in')
      }

      Object.assign(requestOptions.headers, userStore.getAuthHeaders())
    }

    // Send the request
    const response = await fetch(url, requestOptions)

    // Handle API errors
    if (!response.ok) {
      // Try to parse the error message
      let errorMessage = `Request failed: ${response.status}, ${response.statusText}`
      let errorData = null

      console.log('API request failed:', {
        url,
        status: response.status,
        statusText: response.statusText,
        headers: Object.fromEntries(response.headers.entries())
      })

      try {
        errorData = await response.json()
        errorMessage = errorData.detail || errorData.message || errorMessage
        console.log('API error details:', errorData)

        // If this is a 422 error, print more detailed information
        if (response.status === 422) {
          console.error('422 validation error details:', {
            url,
            requestMethod: requestOptions.method,
            requestHeaders: requestOptions.headers,
            requestBody: requestOptions.body,
            responseData: errorData
          })
        }
      } catch (e) {
        // If JSON cannot be parsed, use the default error message
        console.log('Unable to parse error response JSON:', e)
      }

      // Special handling for 401 and 403 errors
      const error = new Error(errorMessage)
      error.response = {
        status: response.status,
        statusText: response.statusText,
        data: errorData
      }

      if (response.status === 401) {
        // If authentication fails, the user may need to log in again
        const userStore = useUserStore()

        // Check whether the token has expired
        const isTokenExpired =
          errorData &&
          (errorData.detail?.includes('token expired') || errorMessage?.includes('token expired'))

        message.error(
          isTokenExpired
            ? 'Login expired, please log in again'
            : 'Authentication failed, please log in again'
        )

        // If the user is currently considered logged in, log them out
        if (userStore.isLoggedIn) {
          userStore.logout()
        }

        // Use setTimeout to ensure the message is shown before redirecting
        setTimeout(() => {
          window.location.href = '/login'
        }, 1500)

        throw error
      } else if (response.status === 403) {
        error.message = 'You do not have permission to perform this action'
        throw error
      } else if (response.status === 500) {
        error.message =
          'Internal server error, use docker logs api-dev to inspect the detailed logs'
        throw error
      }

      throw error
    }

    // Process the response according to responseType
    if (responseType === 'blob') {
      return response
    } else if (responseType === 'json') {
      // Check Content-Type to determine how to handle the response
      const contentType = response.headers.get('Content-Type')
      if (contentType && contentType.includes('application/json')) {
        return await response.json()
      }
      return await response.text()
    } else if (responseType === 'text') {
      return await response.text()
    } else {
      return response
    }
  } catch (error) {
    console.error('API request error:', error)
    throw error
  }
}

/**
 * Send a GET request
 * @param {string} url - API endpoint
 * @param {Object} options - Request options
 * @param {boolean} requiresAuth - Whether authentication is required
 * @param {string} responseType - Response type: 'json' | 'text' | 'blob'
 * @returns {Promise} - Request result
 */
export function apiGet(url, options = {}, requiresAuth = true, responseType = 'json') {
  return apiRequest(url, { method: 'GET', ...options }, requiresAuth, responseType)
}

export function apiAdminGet(url, options = {}, responseType = 'json') {
  checkAdminPermission()
  return apiGet(url, options, true, responseType)
}

export function apiSuperAdminGet(url, options = {}, responseType = 'json') {
  checkSuperAdminPermission()
  return apiGet(url, options, true, responseType)
}

/**
 * Send a POST request
 * @param {string} url - API endpoint
 * @param {Object} data - Request body data
 * @param {Object} options - Other request options
 * @param {boolean} requiresAuth - Whether authentication is required
 * @param {string} responseType - Response type: 'json' | 'text' | 'blob'
 * @returns {Promise} - Request result
 */
export function apiPost(url, data = {}, options = {}, requiresAuth = true, responseType = 'json') {
  return apiRequest(
    url,
    {
      method: 'POST',
      body: data instanceof FormData ? data : JSON.stringify(data),
      ...options
    },
    requiresAuth,
    responseType
  )
}

export function apiAdminPost(url, data = {}, options = {}, responseType = 'json') {
  checkAdminPermission()
  return apiPost(url, data, options, true, responseType)
}

export function apiSuperAdminPost(url, data = {}, options = {}, responseType = 'json') {
  checkSuperAdminPermission()
  return apiPost(url, data, options, true, responseType)
}

/**
 * Send a PUT request
 * @param {string} url - API endpoint
 * @param {Object} data - Request body data
 * @param {Object} options - Other request options
 * @param {boolean} requiresAuth - Whether authentication is required
 * @param {string} responseType - Response type: 'json' | 'text' | 'blob'
 * @returns {Promise} - Request result
 */
export function apiPut(url, data = {}, options = {}, requiresAuth = true, responseType = 'json') {
  return apiRequest(
    url,
    {
      method: 'PUT',
      body: data instanceof FormData ? data : JSON.stringify(data),
      ...options
    },
    requiresAuth,
    responseType
  )
}

export function apiAdminPut(url, data = {}, options = {}, responseType = 'json') {
  checkAdminPermission()
  return apiPut(url, data, options, true, responseType)
}

export function apiSuperAdminPut(url, data = {}, options = {}, responseType = 'json') {
  checkSuperAdminPermission()
  return apiPut(url, data, options, true, responseType)
}

/**
 * Send a DELETE request
 * @param {string} url - API endpoint
 * @param {Object} options - Request options
 * @param {boolean} requiresAuth - Whether authentication is required
 * @param {string} responseType - Response type: 'json' | 'text' | 'blob'
 * @returns {Promise} - Request result
 */
export function apiDelete(url, options = {}, requiresAuth = true, responseType = 'json') {
  return apiRequest(url, { method: 'DELETE', ...options }, requiresAuth, responseType)
}

export function apiAdminDelete(url, options = {}) {
  checkAdminPermission()
  return apiDelete(url, options, true)
}

export function apiSuperAdminDelete(url, options = {}) {
  checkSuperAdminPermission()
  return apiDelete(url, options, true)
}
