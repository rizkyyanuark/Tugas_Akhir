import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAgentStore } from './agent'

export const useUserStore = defineStore('user', () => {
  // State
  const token = ref(localStorage.getItem('user_token') || '')
  const userId = ref(null)
  const username = ref('')
  const userIdLogin = ref('')
  const phoneNumber = ref('')
  const avatar = ref('')
  const userRole = ref('')
  const departmentId = ref(null)
  const departmentName = ref('')

  // Computed properties
  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => userRole.value === 'admin' || userRole.value === 'superadmin')
  const isSuperAdmin = computed(() => userRole.value === 'superadmin')

  // Actions
  async function login(credentials) {
    try {
      const formData = new FormData()
      // Support user_id or phone_number login
      formData.append('username', credentials.loginId) // Use loginId as universal login identifier
      formData.append('password', credentials.password)

      const response = await fetch('/api/auth/token', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        const error = await response.json()

        // If 423 locked status code, throw error with status code
        if (response.status === 423) {
          const lockError = new Error(error.detail || 'Account is locked')
          lockError.status = 423
          lockError.headers = response.headers
          throw lockError
        }

        throw new Error(error.detail || 'Login failed')
      }

      const data = await response.json()

      // Update state
      token.value = data.access_token
      userId.value = data.user_id
      username.value = data.username
      userIdLogin.value = data.user_id_login
      phoneNumber.value = data.phone_number || ''
      avatar.value = data.avatar || ''
      userRole.value = data.role
      departmentId.value = data.department_id || null
      departmentName.value = data.department_name || ''

      // Save only token to local storage
      localStorage.setItem('user_token', data.access_token)

      return true
    } catch (error) {
      console.error('Login error:', error)
      throw error
    }
  }

  function logout() {
    // Clear state
    token.value = ''
    userId.value = null
    username.value = ''
    userIdLogin.value = ''
    phoneNumber.value = ''
    avatar.value = ''
    userRole.value = ''
    departmentId.value = null
    departmentName.value = ''

    // Clear agentStore state to ensure correct data loading on re-login
    const agentStore = useAgentStore()
    agentStore.reset()

    // Clear only token
    localStorage.removeItem('user_token')
  }

  async function initialize(admin) {
    try {
      const response = await fetch('/api/auth/initialize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(admin)
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to initialize admin')
      }

      const data = await response.json()

      // Update state
      token.value = data.access_token
      userId.value = data.user_id
      username.value = data.username
      userIdLogin.value = data.user_id_login
      phoneNumber.value = data.phone_number || ''
      avatar.value = data.avatar || ''
      userRole.value = data.role
      departmentId.value = data.department_id || null
      departmentName.value = data.department_name || ''

      // Save only token to local storage
      localStorage.setItem('user_token', data.access_token)

      return true
    } catch (error) {
      console.error('Initialize admin error:', error)
      throw error
    }
  }

  async function checkFirstRun() {
    try {
      const response = await fetch('/api/auth/check-first-run')
      const data = await response.json()
      return data.first_run
    } catch (error) {
      console.error('Check first run status error:', error)
      return false
    }
  }

  // Authorization header for API requests
  function getAuthHeaders() {
    return {
      Authorization: `Bearer ${token.value}`
    }
  }

  // User management functions
  async function getUsers() {
    try {
      const response = await fetch('/api/auth/users', {
        headers: {
          ...getAuthHeaders()
        }
      })

      if (!response.ok) {
        throw new Error('Failed to fetch user list')
      }

      return await response.json()
    } catch (error) {
      console.error('Get user list error:', error)
      throw error
    }
  }

  async function createUser(userData) {
    try {
      const response = await fetch('/api/auth/users', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify(userData)
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create user')
      }

      return await response.json()
    } catch (error) {
      console.error('Create user error:', error)
      throw error
    }
  }

  async function updateUser(userId, userData) {
    try {
      const response = await fetch(`/api/auth/users/${userId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify(userData)
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to update user')
      }

      return await response.json()
    } catch (error) {
      console.error('Update user error:', error)
      throw error
    }
  }

  async function deleteUser(userId) {
    try {
      const response = await fetch(`/api/auth/users/${userId}`, {
        method: 'DELETE',
        headers: {
          ...getAuthHeaders()
        }
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to delete user')
      }

      return await response.json()
    } catch (error) {
      console.error('Delete user error:', error)
      throw error
    }
  }

  // Validate username and generate user_id
  async function validateUsernameAndGenerateUserId(username) {
    try {
      const response = await fetch('/api/auth/validate-username', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify({ username })
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Username validation failed')
      }

      return await response.json()
    } catch (error) {
      console.error('Username validation error:', error)
      throw error
    }
  }

  // Upload avatar
  async function uploadAvatar(file) {
    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch('/api/auth/upload-avatar', {
        method: 'POST',
        headers: {
          ...getAuthHeaders()
        },
        body: formData
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Avatar upload failed')
      }

      const data = await response.json()

      // Update local avatar state
      avatar.value = data.avatar_url

      return data
    } catch (error) {
      console.error('Avatar upload error:', error)
      throw error
    }
  }

  // Get current user info
  async function getCurrentUser() {
    try {
      const response = await fetch('/api/auth/me', {
        headers: {
          ...getAuthHeaders()
        }
      })

      if (!response.ok) {
        throw new Error('Failed to get user info')
      }

      const userData = await response.json()

      // Update local state
      userId.value = userData.id
      username.value = userData.username
      userIdLogin.value = userData.user_id
      phoneNumber.value = userData.phone_number || ''
      avatar.value = userData.avatar || ''
      userRole.value = userData.role
      departmentId.value = userData.department_id || null
      departmentName.value = userData.department_name || ''

      return userData
    } catch (error) {
      console.error('Get user info error:', error)
      throw error
    }
  }

  // Update profile
  async function updateProfile(profileData) {
    try {
      const response = await fetch('/api/auth/profile', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify(profileData)
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to update profile')
      }

      const userData = await response.json()

      // Update local state
      if (typeof userData.username === 'string') {
        username.value = userData.username
      }
      if (typeof userData.phone_number !== 'undefined') {
        phoneNumber.value = userData.phone_number || ''
      }

      return userData
    } catch (error) {
      console.error('Update profile error:', error)
      throw error
    }
  }

  return {
    // State
    token,
    userId,
    username,
    userIdLogin,
    phoneNumber,
    avatar,
    userRole,
    departmentId,
    departmentName,

    // Computed properties
    isLoggedIn,
    isAdmin,
    isSuperAdmin,

    // Methods
    login,
    logout,
    initialize,
    checkFirstRun,
    getAuthHeaders,
    getUsers,
    createUser,
    updateUser,
    deleteUser,
    validateUsernameAndGenerateUserId,
    uploadAvatar,
    getCurrentUser,
    updateProfile
  }
})

// Check if current user has admin permission
export const checkAdminPermission = () => {
  const userStore = useUserStore()
  if (!userStore.isAdmin) {
    throw new Error('Admin permission required')
  }
  return true
}

// Check if current user has super admin permission
export const checkSuperAdminPermission = () => {
  const userStore = useUserStore()
  return userStore.isSuperAdmin
}
