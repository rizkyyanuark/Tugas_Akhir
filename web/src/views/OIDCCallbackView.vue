<template>
  <div class="oidc-callback-view">
    <div class="callback-container">
      <div v-if="loading" class="loading-section">
        <a-spin size="large" />
        <p class="loading-text">Processing login...</p>
      </div>

      <div v-else-if="error" class="error-section">
        <a-result status="error" :title="errorTitle" :sub-title="errorMessage">
          <template #extra>
            <a-button type="primary" @click="goToLogin"> Back to Login </a-button>
          </template>
        </a-result>
      </div>

      <div v-else class="success-section">
        <a-result status="success" title="Login Successful" sub-title="Redirecting...">
          <template #icon>
            <a-spin />
          </template>
        </a-result>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useAgentStore } from '@/stores/agent'
import { authApi } from '@/apis/auth_api'
import { message } from 'ant-design-vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const agentStore = useAgentStore()

// State
const loading = ref(true)
const error = ref(false)
const errorTitle = ref('Login Failed')
const errorMessage = ref('An error occurred while processing the login request')

// Navigate back to login page
const goToLogin = () => {
  router.push('/login')
}

// Handle OIDC callback - get one-time code from URL query params
const handleCallback = async () => {
  try {
    const code = route.query.code

    // Check required parameters
    if (!code || typeof code !== 'string') {
      loading.value = false
      error.value = true
      errorTitle.value = 'Parameter Error'
      errorMessage.value = 'Missing valid login code, please log in again'
      return
    }

    const tokenData = await authApi.exchangeOIDCCode(code)

    await router.replace({ path: route.path, query: {} })

    // Update user state
    userStore.token = tokenData.access_token
    userStore.userId = tokenData.user_id
    userStore.username = tokenData.username
    userStore.userIdLogin = tokenData.user_id_login || ''
    userStore.phoneNumber = tokenData.phone_number || ''
    userStore.avatar = tokenData.avatar || ''
    userStore.userRole = tokenData.role || 'user'
    userStore.departmentId = tokenData.department_id || null
    userStore.departmentName = tokenData.department_name || ''

    // Save token to localStorage
    localStorage.setItem('user_token', tokenData.access_token)

    // Show success message
    message.success('Login successful')

    // Get redirect path
    const redirectPath = sessionStorage.getItem('oidc_redirect') || '/'
    sessionStorage.removeItem('oidc_redirect')

    loading.value = false

    // Delay redirect so users can see success state
    setTimeout(async () => {
      // Redirect
      if (redirectPath === '/') {
        try {
          await agentStore.initialize()
          router.push('/agent')
        } catch (err) {
          console.error('Failed to get agent info:', err)
          router.push('/agent')
        }
      } else {
        router.push(redirectPath)
      }
    }, 500)
  } catch (err) {
    console.error('OIDC callback processing failed:', err)
    loading.value = false
    error.value = true
    errorTitle.value = 'Login Failed'
    errorMessage.value =
      err?.message || 'An error occurred while processing the login request, please try again'
  }
}

// Handle callback on component mount
onMounted(async () => {
  // If already logged in, redirect to home page
  if (userStore.isLoggedIn) {
    router.push('/')
    return
  }

  await handleCallback()
})
</script>

<style lang="less" scoped>
.oidc-callback-view {
  min-height: 100vh;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--gray-10);
  background-image: radial-gradient(var(--gray-200) 1px, transparent 1px);
  background-size: 24px 24px;
}

.callback-container {
  width: 100%;
  max-width: 500px;
  padding: 40px;
  background: var(--gray-0);
  border-radius: 16px;
  box-shadow: 0 4px 20px var(--shadow-1);
}

.loading-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;

  .loading-text {
    font-size: 16px;
    color: var(--gray-600);
    margin: 0;
  }
}

.error-section,
.success-section {
  :deep(.ant-result) {
    padding: 0;

    .ant-result-title {
      font-size: 20px;
      color: var(--gray-800);
    }

    .ant-result-subtitle {
      font-size: 14px;
      color: var(--gray-500);
    }
  }
}

@media (max-width: 576px) {
  .callback-container {
    margin: 20px;
    padding: 30px 20px;
  }
}
</style>
