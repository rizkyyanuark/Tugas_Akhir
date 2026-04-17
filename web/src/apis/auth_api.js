/**
 * Authentication-related API
 */

async function parseErrorDetail(response, fallbackMessage) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    const error = await response.json()
    return error?.detail || fallbackMessage
  }

  const text = (await response.text()).trim()
  return text || fallbackMessage
}

/**
 * Get the OIDC configuration
 * @returns {Promise<{enabled: boolean, provider_name?: string}>}
 */
async function getOIDCConfig() {
  const response = await fetch('/api/auth/oidc/config')
  if (!response.ok) {
    throw new Error('Failed to get OIDC configuration')
  }
  return response.json()
}

/**
 * Get the OIDC login URL
 * @param {string} redirectPath - Redirect path after login
 * @returns {Promise<{login_url: string}>}
 */
async function getOIDCLoginUrl(redirectPath = '/') {
  const params = new URLSearchParams({ redirect_path: redirectPath })
  const response = await fetch(`/api/auth/oidc/login-url?${params}`)
  if (!response.ok) {
    const detail = await parseErrorDetail(response, 'Failed to get the OIDC login URL')
    throw new Error(detail)
  }
  return response.json()
}

/**
 * Exchange the OIDC login result using a one-time code
 * @param {string} code - One-time login code
 * @returns {Promise<{
 *   access_token: string,
 *   token_type: string,
 *   user_id: number,
 *   username: string,
 *   user_id_login: string,
 *   phone_number: string | null,
 *   avatar: string | null,
 *   role: string,
 *   department_id: number | null,
 *   department_name: string | null
 * }>}
 */
async function exchangeOIDCCode(code) {
  const response = await fetch('/api/auth/oidc/exchange-code', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ code })
  })

  if (!response.ok) {
    const detail = await parseErrorDetail(response, 'OIDC login failed')
    throw new Error(detail)
  }

  return response.json()
}

export const authApi = {
  getOIDCConfig,
  getOIDCLoginUrl,
  exchangeOIDCCode
}
