<template>
  <div class="login-view" :class="{ 'has-alert': serverStatus === 'error' }">
    <!-- Server status alert -->
    <div v-if="serverStatus === 'error'" class="server-status-alert">
      <div class="alert-content">
        <exclamation-circle-icon class="alert-icon" size="20" />
        <div class="alert-text">
          <div class="alert-title">Server Connection Failed</div>
          <div class="alert-message">{{ serverError }}</div>
        </div>
        <a-button type="link" size="small" @click="checkServerHealth" :loading="healthChecking">
          Retry
        </a-button>
      </div>
    </div>

    <!-- Top navigation: Brand name & action buttons -->
    <nav class="login-navbar">
      <div class="navbar-content">
        <div class="brand-container" @click="goHome" style="cursor: pointer">
          <img v-if="brandLogo" :src="brandLogo" alt="logo" class="brand-logo" />
          <h1 class="brand-text">
            <span v-if="brandOrgName" class="brand-org">{{ brandOrgName }}</span>
            <span v-if="brandOrgName && brandName !== brandOrgName" class="brand-separator"></span>
            <span class="brand-main">{{ brandName }}</span>
          </h1>
        </div>
      </div>
    </nav>

    <!-- Main content area: centered card -->
    <main class="login-main">
      <div class="login-card">
        <!-- Left side image -->
        <div class="card-side is-image">
          <img :src="loginBgImage" alt="Login background" class="login-bg-image" />
        </div>

        <!-- Right side form -->
        <div class="card-side is-form">
          <div class="form-wrapper">
            <header class="form-header">
              <!-- Show specific title during initialization -->
              <h2 v-if="isFirstRun" class="init-title">System Initialization — Create Super Admin</h2>
              <p v-else class="welcome-text">Welcome Back</p>
            </header>

            <div class="login-content" :class="{ 'is-initializing': isFirstRun }">
              <!-- Admin initialization form -->
              <div v-if="isFirstRun" class="login-form login-form--init">
                <a-form :model="adminForm" @finish="handleInitialize" layout="vertical">
                  <a-form-item
                    label="User ID"
                    name="user_id"
                    :rules="[
                      { required: true, message: 'Please enter a User ID' },
                      {
                        pattern: /^[a-zA-Z0-9_]+$/,
                        message: 'User ID can only contain letters, numbers, and underscores'
                      },
                      {
                        min: 3,
                        max: 20,
                        message: 'User ID must be between 3-20 characters'
                      }
                    ]"
                  >
                    <a-input
                      v-model:value="adminForm.user_id"
                      placeholder="Enter User ID (3-20 characters)"
                      :maxlength="20"
                    />
                  </a-form-item>

                  <a-form-item
                    label="Phone Number (Optional)"
                    name="phone_number"
                    :rules="[
                      {
                        validator: async (rule, value) => {
                          if (!value || value.trim() === '') {
                            return // empty value allowed
                          }
                          const phoneRegex = /^[0-9]{10,15}$/
                          if (!phoneRegex.test(value)) {
                            throw new Error('Please enter a valid phone number')
                          }
                        }
                      }
                    ]"
                  >
                    <a-input
                      v-model:value="adminForm.phone_number"
                      placeholder="Can be used for login (optional)"
                      :max-length="15"
                    />
                  </a-form-item>

                  <a-form-item
                    label="Password"
                    name="password"
                    :rules="[{ required: true, message: 'Please enter a password' }]"
                  >
                    <a-input-password v-model:value="adminForm.password" prefix-icon="lock" />
                  </a-form-item>

                  <a-form-item
                    label="Confirm Password"
                    name="confirmPassword"
                    :rules="[
                      { required: true, message: 'Please confirm your password' },
                      { validator: validateConfirmPassword }
                    ]"
                  >
                    <a-input-password
                      v-model:value="adminForm.confirmPassword"
                      prefix-icon="lock"
                    />
                  </a-form-item>

                  <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                    <div class="agreement-row">
                      <a-checkbox v-model:checked="agreementAccepted">
                        By signing in, you agree to the
                        <a
                          class="agreement-link"
                          :href="userAgreementUrl"
                          target="_blank"
                          rel="noopener noreferrer"
                          @click.stop
                          >Terms of Service</a
                        >
                        and
                        <a
                          class="agreement-link"
                          :href="privacyPolicyUrl"
                          target="_blank"
                          rel="noopener noreferrer"
                          @click.stop
                          >Privacy Policy</a
                        >
                      </a-checkbox>
                    </div>
                  </a-form-item>

                  <a-form-item>
                    <a-button type="primary" html-type="submit" :loading="loading" block
                      >Create Admin Account</a-button
                    >
                  </a-form-item>
                </a-form>
              </div>

              <!-- Login form -->
              <div v-else class="login-form">
                <a-form :model="loginForm" @finish="handleLogin" layout="vertical">
                  <a-form-item
                    label="Login Account"
                    name="loginId"
                    :rules="[{ required: true, message: 'Please enter your User ID or phone number' }]"
                  >
                    <a-input v-model:value="loginForm.loginId" placeholder="User ID or phone number">
                      <template #prefix>
                        <user-icon size="18" />
                      </template>
                    </a-input>
                  </a-form-item>

                  <a-form-item
                    label="Password"
                    name="password"
                    :rules="[{ required: true, message: 'Please enter your password' }]"
                  >
                    <a-input-password v-model:value="loginForm.password">
                      <template #prefix>
                        <lock-icon size="18" />
                      </template>
                    </a-input-password>
                  </a-form-item>

                  <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                    <div class="agreement-row">
                      <a-checkbox v-model:checked="agreementAccepted">
                        By signing in, you agree to the
                        <a
                          class="agreement-link"
                          :href="userAgreementUrl"
                          target="_blank"
                          rel="noopener noreferrer"
                          @click.stop
                          >Terms of Service</a
                        >
                        and
                        <a
                          class="agreement-link"
                          :href="privacyPolicyUrl"
                          target="_blank"
                          rel="noopener noreferrer"
                          @click.stop
                          >Privacy Policy</a
                        >
                      </a-checkbox>
                    </div>
                  </a-form-item>

                  <a-form-item>
                    <a-button
                      type="primary"
                      html-type="submit"
                      :loading="loading"
                      :disabled="isLocked"
                      block
                      size="large"
                    >
                      <span v-if="isLocked">Account Locked {{ formatTime(lockRemainingTime) }}</span>
                      <span v-else>Sign In</span>
                    </a-button>
                  </a-form-item>
                </a-form>

                <!-- OIDC login options  -->
                <div v-if="oidcChecking || oidcEnabled" class="third-party-login">
                  <div class="divider">
                    <span>Or sign in with</span>
                  </div>
                  <div class="login-icons">
                    <!-- Show skeleton while checking -->
                    <div v-if="oidcChecking" class="login-skeleton">
                      <a-skeleton-button block size="large" :active="true" />
                    </div>
                    <!-- Show button after check completes -->
                    <a-button
                      v-else
                      type="default"
                      size="large"
                      block
                      :loading="oidcLoading"
                      @click="handleOIDCLogin"
                    >
                      <template #icon>
                        <key-icon size="18" />
                      </template>
                      {{ oidcButtonText }}
                    </a-button>
                  </div>
                </div>
              </div>

              <!-- Error message -->
              <div v-if="errorMessage" class="error-message">
                {{ errorMessage }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- Page footer: copyright, etc. -->
    <footer class="page-footer">
      <div class="footer-links">
        <a href="https://github.com/xerrors" target="_blank">Contact Us</a>
        <span class="divider">|</span>
        <a href="https://github.com/xerrors/agenticrag" target="_blank">Help</a>
      </div>
      <div class="copyright">
        &copy; {{ new Date().getFullYear() }} {{ brandName }}. All Rights Reserved.
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useInfoStore } from '@/stores/info'
import { useAgentStore } from '@/stores/agent'
import { message } from 'ant-design-vue'
import { healthApi } from '@/apis/system_api'
import { authApi } from '@/apis/auth_api'
import {
  User as UserIcon,
  Lock as LockIcon,
  Key as KeyIcon,
  AlertCircle as ExclamationCircleIcon
} from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const infoStore = useInfoStore()
const STAR_CARD_STORAGE_KEY = 'agenticrag-settings-star-card-dismissed'
const agentStore = useAgentStore()

// Brand display data
const loginBgImage = computed(() => {
  return infoStore.organization?.login_bg || '/login-bg.jpg'
})
const brandLogo = computed(() => {
  return infoStore.organization?.logo || ''
})
const brandOrgName = computed(() => {
  return infoStore.organization?.name?.trim() || ''
})
const brandName = computed(() => {
  const orgName = brandOrgName.value
  const brandNameRaw = infoStore.branding?.name?.trim() || 'agenticrag'

  if (orgName && brandNameRaw && orgName !== brandNameRaw) {
    return brandNameRaw
  }

  return orgName || brandNameRaw
})
const userAgreementUrl = computed(() => {
  return infoStore.footer?.user_agreement_url?.trim() || ''
})
const privacyPolicyUrl = computed(() => {
  return infoStore.footer?.privacy_policy_url?.trim() || ''
})
const showAgreementConsent = computed(() => {
  return Boolean(userAgreementUrl.value && privacyPolicyUrl.value)
})

// State
const isFirstRun = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const agreementAccepted = ref(false)
const serverStatus = ref('loading')
const serverError = ref('')
const healthChecking = ref(false)

// OIDC related state
const oidcEnabled = ref(false)
const oidcLoading = ref(false)
const oidcChecking = ref(true)
const oidcButtonText = ref('OIDC Login')

// Login lock state
const isLocked = ref(false)
const lockRemainingTime = ref(0)
const lockCountdown = ref(null)

// Login form
const loginForm = reactive({
  loginId: '', // Supports user_id or phone_number login
  password: ''
})

// Admin initialization form
const adminForm = reactive({
  user_id: '', // Direct user_id input
  password: '',
  confirmPassword: '',
  phone_number: '' // Phone number field (optional)
})

const goHome = () => {
  router.push('/')
}

// Clear countdown timer
const clearLockCountdown = () => {
  if (lockCountdown.value) {
    clearInterval(lockCountdown.value)
    lockCountdown.value = null
  }
}

// Start lock countdown
const startLockCountdown = (remainingSeconds) => {
  clearLockCountdown()
  isLocked.value = true
  lockRemainingTime.value = remainingSeconds

  lockCountdown.value = setInterval(() => {
    lockRemainingTime.value--
    if (lockRemainingTime.value <= 0) {
      clearLockCountdown()
      isLocked.value = false
      errorMessage.value = ''
    }
  }, 1000)
}

// Format time display
const formatTime = (seconds) => {
  if (seconds < 60) {
    return `${seconds}s`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  } else if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}h ${minutes}m`
  } else {
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    return `${days}d ${hours}h`
  }
}

// Password confirmation validation
const validateConfirmPassword = async (rule, value) => {
  if (value === '') {
    throw new Error('Please confirm your password')
  }
  if (value !== adminForm.password) {
    throw new Error('Passwords do not match')
  }
}

const ensureAgreementAccepted = () => {
  if (!showAgreementConsent.value || agreementAccepted.value) {
    return true
  }

  const warningMessage = 'Please read and agree to the Terms of Service and Privacy Policy'
  message.warning(warningMessage)
  return false
}

// Handle login
const handleLogin = async () => {
  // If currently locked, do not allow login
  if (isLocked.value) {
    message.warning(`Account is locked, please wait ${formatTime(lockRemainingTime.value)}`)
    return
  }

  if (!ensureAgreementAccepted()) {
    return
  }

  try {
    loading.value = true
    errorMessage.value = ''
    clearLockCountdown()

    await userStore.login({
      loginId: loginForm.loginId,
      password: loginForm.password
    })

    message.success('Login successful')

    // Get redirect path
    const redirectPath = sessionStorage.getItem('redirect') || '/'
    sessionStorage.removeItem('redirect') // Clear redirect info

    // Determine redirect target based on user role
    if (redirectPath === '/') {
      // Redirect to chat page (shared between admin and regular users)
      try {
        await agentStore.initialize()
        router.push('/agent')
      } catch (error) {
        console.error('Failed to get agent info:', error)
        router.push('/agent')
      }
    } else {
      // Redirect to other preset path
      router.push(redirectPath)
    }
  } catch (error) {
    console.error('Login failed:', error)

    // Check if it's a lock error (HTTP 423)
    if (error.status === 423) {
      // Try to get remaining time from response headers
      let remainingTime = 0
      if (error.headers && error.headers.get) {
        const lockRemainingHeader = error.headers.get('X-Lock-Remaining')
        if (lockRemainingHeader) {
          remainingTime = parseInt(lockRemainingHeader)
        }
      }

      // If not obtained from headers, try to parse from error message
      if (remainingTime === 0) {
        const lockTimeMatch = error.message.match(/(\d+)\s*s/)
        if (lockTimeMatch) {
          remainingTime = parseInt(lockTimeMatch[1])
        }
      }

      if (remainingTime > 0) {
        startLockCountdown(remainingTime)
        errorMessage.value = `Account has been locked due to multiple failed login attempts. ${formatTime(remainingTime)}`
      } else {
        errorMessage.value = error.message || 'Account is locked, please try again later'
      }
    } else {
      errorMessage.value = error.message || 'Login failed, please check your username and password'
    }
  } finally {
    loading.value = false
  }
}

// Handle OIDC login
const handleOIDCLogin = async () => {
  if (!ensureAgreementAccepted()) {
    return
  }

  try {
    oidcLoading.value = true
    errorMessage.value = ''

    // Get OIDC login URL
    const response = await authApi.getOIDCLoginUrl()
    if (response.login_url) {
      // Save current path for redirect after login
      const redirectPath =
        sessionStorage.getItem('redirect') || router.currentRoute.value.query.redirect || '/'
      sessionStorage.setItem('oidc_redirect', redirectPath)

      // Redirect to OIDC Provider
      window.location.href = response.login_url
    } else {
      errorMessage.value = 'Failed to get OIDC login URL'
    }
  } catch (error) {
    console.error('OIDC login failed:', error)
    errorMessage.value = error.message || 'OIDC login failed, please try again'
  } finally {
    oidcLoading.value = false
  }
}

// Check OIDC configuration
const checkOIDCConfig = async () => {
  oidcChecking.value = true
  try {
    const config = await authApi.getOIDCConfig()
    oidcEnabled.value = config.enabled
    if (config.provider_name) {
      oidcButtonText.value = config.provider_name
    }
  } catch (error) {
    console.error('OIDC config check failed:', error)
    oidcEnabled.value = false
  } finally {
    oidcChecking.value = false
  }
}

// Handle admin initialization
const handleInitialize = async () => {
  if (!ensureAgreementAccepted()) {
    return
  }

  try {
    loading.value = true
    errorMessage.value = ''

    if (adminForm.password !== adminForm.confirmPassword) {
      errorMessage.value = 'Passwords do not match'
      return
    }

    await userStore.initialize({
      user_id: adminForm.user_id,
      password: adminForm.password,
      phone_number: adminForm.phone_number || null // Convert empty string to null
    })

    message.success('Admin account created successfully')
    router.push('/')
  } catch (error) {
    console.error('Initialization failed:', error)
    errorMessage.value = error.message || 'Initialization failed, please try again'
  } finally {
    loading.value = false
  }
}

// Check first run status
const checkFirstRunStatus = async () => {
  try {
    loading.value = true
    const isFirst = await userStore.checkFirstRun()
    isFirstRun.value = isFirst
  } catch (error) {
    console.error('First run status check failed:', error)
    errorMessage.value = 'System error, please try again later'
  } finally {
    loading.value = false
  }
}

// Check server health status
const checkServerHealth = async () => {
  try {
    healthChecking.value = true
    const response = await healthApi.checkHealth()
    if (response.status === 'ok') {
      serverStatus.value = 'ok'
    } else {
      serverStatus.value = 'error'
      serverError.value = response.message || 'Server status abnormal'
    }
  } catch (error) {
    console.error('Server health check failed:', error)
    serverStatus.value = 'error'
    serverError.value = error.message || 'Cannot connect to server, please check your network'
  } finally {
    healthChecking.value = false
  }
}

// On component mount
onMounted(async () => {
  // If already logged in, redirect to home
  if (userStore.isLoggedIn) {
    router.push('/')
    return
  }

  // Show OIDC auth failure error message (carried by backend redirect)
  if (route.query.oidc_error) {
    errorMessage.value = String(route.query.oidc_error)
  }

  // First check server health status
  await checkServerHealth()

  // Check if this is the first run
  await checkFirstRunStatus()

  // Check OIDC configuration
  checkOIDCConfig()
})

// Clean up timers on component unmount
onUnmounted(() => {
  clearLockCountdown()
})
</script>

<style lang="less" scoped>
.login-view {
  min-height: 100vh;
  width: 100%;
  position: relative;
  display: flex;
  flex-direction: column;
  background-color: var(--gray-10);
  background-image: radial-gradient(var(--gray-200) 1px, transparent 1px);
  background-size: 24px 24px;

  &.has-alert {
    padding-top: 60px;
  }
}

/* Unified Navbar */
.login-navbar {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  padding: 32px 0;
  z-index: 10;

  .navbar-content {
    max-width: 1500px; /* Constraint the width */
    margin: 0 auto;
    padding: 0 40px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    .brand-container {
      display: flex;
      align-items: center;
      gap: 12px;
    }
  }
}

.brand-text {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  line-height: 1;
  display: flex;
  align-items: center;
  gap: 12px;

  .brand-org {
    color: var(--gray-700);
    font-weight: 600;
  }

  .brand-separator {
    width: 4px;
    height: 4px;
    background-color: var(--gray-400);
    border-radius: 50%;
    font-weight: 600;
  }

  .brand-main {
    color: var(--main-color);
    font-weight: 600;
  }
}

.brand-logo {
  height: 32px;
  width: auto;
  object-fit: contain;
}

.top-logo {
  height: 32px;
  width: auto;
  object-fit: contain;
}

.back-home-btn {
  color: var(--gray-600);
  font-size: 14px;
  &:hover {
    color: var(--main-color);
    background-color: transparent;
  }
}

/* Main Content: Card Layout */
.login-main {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  padding-top: 80px; /* Add space for navbar */
}

.login-card {
  width: 900px;
  max-width: 95vw;
  height: 560px;
  background: var(--gray-0);
  border-radius: 16px;
  box-shadow: 0 0px 40px var(--shadow-1);
  display: flex;
  overflow: hidden;
}

.card-side {
  position: relative;
}

/* Image Side */
.card-side.is-image {
  flex: 1.4;
  background-color: var(--main-10);
  overflow: hidden;

  .login-bg-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }
}

/* Form Side */
.card-side.is-form {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.form-wrapper {
  width: 100%;
  max-width: 320px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.form-header {
  text-align: left;
  .welcome-text {
    font-size: 14px;
    font-weight: 600;
    color: var(--gray-500);
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .init-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--main-color);
    margin: 0;
    line-height: 1.4;
  }
}

.login-form {
  :deep(.ant-input-affix-wrapper) {
    padding: 10px 12px;
    border-radius: 8px;
  }
  :deep(.ant-btn) {
    height: 44px;
    font-size: 16px;
    border-radius: 8px;
  }
  :deep(.ant-input-prefix) {
    margin-right: 8px;
    color: var(--gray-500);
  }
}

.login-form.login-form--init :deep(.ant-form-item) {
  margin-bottom: 14px;
}

.third-party-login {
  margin-top: 16px;
  .divider {
    position: relative;
    text-align: center;
    margin: 24px 0 16px;
    &::before,
    &::after {
      content: '';
      position: absolute;
      top: 50%;
      width: 30%;
      height: 1px;
      background-color: var(--gray-200);
    }
    &::before {
      left: 0;
    }
    &::after {
      right: 0;
    }
    span {
      display: inline-block;
      padding: 0 8px;
      background-color: var(--gray-0);
      color: var(--gray-400);
      font-size: 12px;
    }
  }

  .login-icons {
    :deep(.ant-btn) {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border-color: var(--gray-300);
      color: var(--gray-700);

      &:hover {
        border-color: var(--main-color);
        color: var(--main-color);
        background-color: var(--main-10);
      }

      .anticon,
      svg {
        color: var(--main-color);
      }
    }
  }

  /* Fix: add skeleton screen styles */
  .login-skeleton {
    :deep(.ant-skeleton-button) {
      width: 100% !important;
      height: 44px;
      border-radius: 8px;
    }
  }
}

.agreement-form-item {
  margin-bottom: 12px;
}

.agreement-row {
  font-size: 13px;
  color: var(--gray-600);
  line-height: 1.6;

  :deep(.ant-checkbox-wrapper) {
    display: inline-flex;
    align-items: flex-start;
  }

  :deep(.ant-checkbox + span) {
    padding-inline-start: 8px;
  }
}

.agreement-link {
  color: var(--main-color);

  &:hover {
    text-decoration: underline;
  }
}

.error-message {
  margin-top: 16px;
  padding: 10px 12px;
  background-color: var(--color-error-50);
  border: 1px solid color-mix(in srgb, var(--color-error-500) 25%, transparent);
  border-radius: 6px;
  color: var(--color-error-700);
  font-size: 13px;
  text-align: center;
}

/* Page Footer */
.page-footer {
  padding: 24px;
  text-align: center;
}

.footer-links {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;

  a {
    color: var(--gray-500);
    font-size: 13px;
    &:hover {
      color: var(--main-color);
    }
  }

  .divider {
    color: var(--gray-300);
    font-size: 12px;
  }
}

.copyright {
  font-size: 12px;
  color: var(--gray-400);
}

/* Server Status Alert */
.server-status-alert {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 12px 20px;
  background: var(--color-error-500);
  color: var(--gray-0);
  z-index: 1000;

  .alert-content {
    display: flex;
    align-items: center;
    max-width: 1500px;
    margin: 0 auto;

    .alert-icon {
      font-size: 20px;
      margin-right: 12px;
      color: var(--gray-0);
    }

    .alert-text {
      flex: 1;

      .alert-title {
        font-weight: 600;
        font-size: 16px;
        margin-bottom: 2px;
      }

      .alert-message {
        font-size: 14px;
        opacity: 0.9;
      }
    }

    :deep(.ant-btn-link) {
      color: var(--gray-0);
      border-color: var(--gray-0);

      &:hover {
        color: var(--gray-0);
        background-color: color-mix(in srgb, var(--gray-0) 10%, transparent);
      }
    }
  }
}

/* Responsive */
@media (max-width: 1280px) {
  .login-navbar .navbar-content {
    padding: 0 40px;
  }
}

@media (max-width: 768px) {
  .login-navbar .navbar-content {
    padding: 0 20px;
  }

  .brand-text {
    font-size: 20px;
  }

  .login-card {
    flex-direction: column;
    height: auto;
    max-height: none;
    width: 100%;
    margin-top: 20px;
  }

  .card-side.is-image {
    display: none;
  }

  .card-side.is-form {
    padding: 40px 20px;
  }
}
</style>
