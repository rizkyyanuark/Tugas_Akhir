<template>
  <div class="user-info-component">
    <a-dropdown :trigger="['hover']" v-if="userStore.isLoggedIn">
      <div class="user-info-dropdown" :data-align="showRole ? 'left' : 'center'">
        <div class="user-avatar">
          <img
            v-if="userStore.avatar"
            :src="userStore.avatar"
            :alt="userStore.username"
            class="avatar-image"
          />
          <CircleUser v-else />
          <!-- <div class="user-role-badge" :class="userRoleClass"></div> -->
        </div>
        <div v-if="showRole">{{ userStore.username }}</div>
      </div>
      <template #overlay>
        <a-menu>
          <a-menu-item key="user-info" @click="openProfile">
            <div class="user-info-display">
              <div class="user-menu-username">{{ userStore.username }}</div>
              <div class="user-menu-details">
                <span class="user-menu-info">ID: {{ userStore.userIdLogin }}</span>
                <span class="user-menu-role">{{ userRoleText }}</span>
              </div>
            </div>
          </a-menu-item>
          <a-menu-divider />
          <a-menu-item key="docs" @click="openDocs" :icon="BookOpenIcon">
            <span class="menu-text">Documentation</span>
          </a-menu-item>
          <a-menu-item
            key="theme"
            @click="toggleTheme"
            :icon="themeStore.isDark ? SunIcon : MoonIcon"
          >
            <span class="menu-text">{{
              themeStore.isDark ? 'Switch to light mode' : 'Switch to dark mode (Beta)'
            }}</span>
          </a-menu-item>
          <a-menu-divider v-if="userStore.isAdmin" />
          <a-menu-item
            v-if="userStore.isSuperAdmin"
            key="debug"
            @click="showDebug = true"
            :icon="TerminalIcon"
          >
            <span class="menu-text">Debug Panel (Non-production)</span>
          </a-menu-item>
          <a-menu-item
            v-if="userStore.isAdmin"
            key="setting"
            @click="goToSetting"
            :icon="SettingsIcon"
          >
            <span class="menu-text">System Settings</span>
          </a-menu-item>
          <a-menu-item key="logout" @click="logout" :icon="LogOutIcon">
            <span class="menu-text">Sign Out</span>
          </a-menu-item>
        </a-menu>
      </template>
    </a-dropdown>
    <a-button v-else-if="showButton" type="primary" @click="goToLogin"> Login </a-button>

    <!-- Profile modal -->
    <a-modal v-model:open="profileModalVisible" :footer="null" width="420px" class="profile-modal">
      <div class="profile-content">
        <!-- Avatar section -->
        <div class="avatar-section">
          <div class="avatar-container">
            <div class="avatar-display">
              <img
                v-if="userStore.avatar"
                :src="userStore.avatar"
                :alt="userStore.username"
                class="large-avatar"
              />
              <div v-else class="default-avatar">
                <CircleUser :size="60" />
              </div>
            </div>
            <div class="avatar-actions">
              <a-upload
                :show-upload-list="false"
                :before-upload="beforeUpload"
                @change="handleAvatarChange"
                accept="image/*"
              >
                <a-button
                  type="primary"
                  class="lucide-icon-btn"
                  size="small"
                  :loading="avatarUploading"
                >
                  <template #icon><Upload size="14" /></template>
                  {{ userStore.avatar ? 'Change Avatar' : 'Upload Avatar' }}
                </a-button>
              </a-upload>
              <div class="avatar-tips">Supports JPG/PNG, file size up to 5MB</div>
            </div>
          </div>
        </div>

        <!-- User information section -->
        <div class="info-section">
          <div class="info-item">
            <div class="info-label">Username</div>
            <div class="info-value" v-if="!profileEditing">
              {{ userStore.username || 'Not set' }}
            </div>
            <div class="info-value" v-else>
              <a-input
                v-model:value="editedProfile.username"
                placeholder="Enter username (2-20 characters)"
                :max-length="20"
                style="width: 240px"
              />
            </div>
          </div>
          <div class="info-item">
            <div class="info-label">User ID</div>
            <div class="info-value user-id" v-if="!profileEditing">
              {{ userStore.userIdLogin || 'Not set' }}
            </div>
            <div class="info-value" v-else>
              <a-input :value="userStore.userIdLogin || ''" disabled style="width: 240px" />
            </div>
          </div>
          <div class="info-item">
            <div class="info-label">Phone</div>
            <div class="info-value" v-if="!profileEditing">
              {{ userStore.phoneNumber || 'Not set' }}
            </div>
            <div class="info-value" v-else>
              <a-input
                v-model:value="editedProfile.phone_number"
                placeholder="Enter phone number"
                :max-length="11"
                style="width: 200px"
              />
            </div>
          </div>
          <div class="info-item">
            <div class="info-label">Role</div>
            <div class="info-value" :style="{ color: getRoleColor(userStore.userRole) }">
              {{ userRoleText }}
            </div>
          </div>
          <div class="info-item" v-if="userStore.departmentId">
            <div class="info-label">Department</div>
            <div class="info-value">{{ userStore.departmentName || 'Default Department' }}</div>
          </div>
        </div>

        <!-- Actions -->
        <div class="actions-section">
          <a-space>
            <template v-if="!profileEditing">
              <a-button type="primary" @click="startEdit"> Edit Profile </a-button>
              <a-button @click="profileModalVisible = false"> Close </a-button>
            </template>
            <template v-else>
              <a-button type="primary" @click="saveProfile" :loading="avatarUploading">
                Save
              </a-button>
              <a-button @click="cancelEdit"> Cancel </a-button>
            </template>
          </a-space>
        </div>
      </div>
    </a-modal>

    <!-- Debug panel modal -->
    <DebugComponent v-model:show="showDebug" />
  </div>
</template>

<script setup>
import { computed, ref, inject, h } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import DebugComponent from '@/components/DebugComponent.vue'
import { message } from 'ant-design-vue'
import {
  CircleUser,
  BookOpen,
  Sun,
  Moon,
  LogOut,
  Upload,
  Settings,
  Terminal
} from 'lucide-vue-next'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()

// Predefined icon components to avoid Vue warnings
const BookOpenIcon = h(BookOpen, { size: '16' })
const SunIcon = h(Sun, { size: '16' })
const MoonIcon = h(Moon, { size: '16' })
const TerminalIcon = h(Terminal, { size: '16' })
const SettingsIcon = h(Settings, { size: '16' })
const LogOutIcon = h(LogOut, { size: '16' })

// Debug panel state
const showDebug = ref(false)

// Inject settings modal methods
const { openSettingsModal } = inject('settingsModal', {})

// Profile modal state
const profileModalVisible = ref(false)
const avatarUploading = ref(false)
const profileEditing = ref(false)
const editedProfile = ref({
  username: '',
  phone_number: ''
})

defineProps({
  showRole: {
    type: Boolean,
    default: false
  },
  showButton: {
    type: Boolean,
    default: false
  }
})

// User role display text
const userRoleText = computed(() => {
  switch (userStore.userRole) {
    case 'superadmin':
      return 'Super Admin'
    case 'admin':
      return 'Admin'
    case 'user':
      return 'User'
    default:
      return 'Unknown Role'
  }
})

// Sign out
const logout = () => {
  userStore.logout()
  message.success('Signed out successfully')
  // Redirect to login page
  router.push('/login')
}

// Go to login page
const goToLogin = () => {
  router.push('/login')
}

const openDocs = () => {
  window.open('https://xerrors.github.io/Yuxi/', '_blank', 'noopener,noreferrer')
}

const toggleTheme = () => {
  themeStore.toggleTheme()
}

// Open settings
const goToSetting = () => {
  if (openSettingsModal) {
    openSettingsModal()
  }
}

// Open profile modal
const openProfile = async () => {
  profileModalVisible.value = true
  profileEditing.value = false

  // Refresh user info and initialize edit form
  try {
    await userStore.getCurrentUser()
    editedProfile.value = {
      username: userStore.username || '',
      phone_number: userStore.phoneNumber || ''
    }
  } catch (error) {
    console.error('Failed to refresh user information:', error)
  }
}

// Role color
const getRoleColor = (role) => {
  switch (role) {
    case 'superadmin':
      return 'var(--color-error-700)'
    case 'admin':
      return 'var(--color-primary-500)'
    case 'user':
      return 'var(--color-success-500)'
    default:
      return 'default'
  }
}

// Start editing profile
const startEdit = () => {
  profileEditing.value = true
  editedProfile.value = {
    username: userStore.username || '',
    phone_number: userStore.phoneNumber || ''
  }
}

// Cancel editing
const cancelEdit = () => {
  profileEditing.value = false
  editedProfile.value = {
    username: userStore.username || '',
    phone_number: userStore.phoneNumber || ''
  }
}

// Save profile
const saveProfile = async () => {
  try {
    // Validate username
    if (
      editedProfile.value.username &&
      (editedProfile.value.username.trim().length < 2 ||
        editedProfile.value.username.trim().length > 20)
    ) {
      message.error('Username length must be between 2 and 20 characters')
      return
    }

    // Validate phone number format
    if (
      editedProfile.value.phone_number &&
      !validatePhoneNumber(editedProfile.value.phone_number)
    ) {
      message.error('Please enter a valid phone number')
      return
    }

    await userStore.updateProfile({
      username: editedProfile.value.username?.trim() || undefined,
      phone_number: editedProfile.value.phone_number || undefined
    })
    message.success('Profile updated successfully!')
    profileEditing.value = false
  } catch (error) {
    console.error('Failed to update profile:', error)
    message.error('Update failed: ' + (error.message || 'Please try again later'))
  }
}

// Phone number validation
const validatePhoneNumber = (phone) => {
  if (!phone) return true // Empty phone number is allowed
  const phoneRegex = /^(?:\+62|62|0)8[1-9][0-9]{7,10}$/
  return phoneRegex.test(phone)
}

// Validate avatar before upload
const beforeUpload = (file) => {
  const isImage = file.type.startsWith('image/')
  if (!isImage) {
    message.error('Only image files are allowed!')
    return false
  }

  const isLt5M = file.size / 1024 / 1024 < 5
  if (!isLt5M) {
    message.error('Image size cannot exceed 5MB!')
    return false
  }

  return true
}

// Handle avatar upload
const handleAvatarChange = async (info) => {
  if (info.file.status === 'uploading') {
    avatarUploading.value = true
    return
  }

  if (info.file.status === 'done') {
    avatarUploading.value = false
    return
  }

  // Handle file upload manually
  try {
    avatarUploading.value = true
    await userStore.uploadAvatar(info.file.originFileObj || info.file)
    message.success('Avatar uploaded successfully!')
  } catch (error) {
    console.error('Avatar upload failed:', error)
    message.error('Avatar upload failed: ' + (error.message || 'Please try again later'))
  } finally {
    avatarUploading.value = false
  }
}
</script>

<style lang="less" scoped>
.user-info-component {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--gray-800);
  // margin-bottom: 16px;
}

.user-info-dropdown {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;

  &[data-align='center'] {
    justify-content: center;
  }

  &[data-align='left'] {
    justify-content: flex-start;
  }
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 16px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  box-shadow: 0 2px 8px var(--shadow-2);

  &:hover {
    opacity: 0.9;
  }

  .avatar-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
    border-radius: 50%;
    border: 2px solid var(--gray-150);
  }
}

.user-role-badge {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  right: 0;
  bottom: 0;
  border: 2px solid var(--gray-0);

  &.superadmin {
    background-color: var(--color-warning-500);
  }

  &.admin {
    background-color: var(--color-info-500); /* Blue for admin */
  }

  &.user {
    background-color: var(--color-success-500); /* Green for regular user */
  }
}

.user-info-display {
  line-height: 1.4;
}

.user-menu-username {
  font-weight: 600;
  color: var(--gray-900);
  font-size: 14px;
  display: block;
  margin-bottom: 2px;
}

.user-menu-details {
  display: flex;
  gap: 12px;
  align-items: center;
}

.user-menu-info {
  font-size: 12px;
  color: var(--gray-600);
}

.user-menu-role {
  font-size: 12px;
  color: var(--gray-500);
}

.login-icon {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-radius: 50%;
  transition:
    background-color 0.2s,
    color 0.2s;
  color: var(--gray-900);

  &:hover {
    background-color: var(--main-10);
    color: var(--main-color);
  }
}

.profile-modal {
  :deep(.ant-modal-header) {
    padding: 40px 24px;
    border-bottom: 1px solid var(--gray-150);
  }

  :deep(.ant-modal-body) {
    padding: 24px;
  }
}

.profile-content {
  .avatar-section {
    text-align: center;
    margin-bottom: 32px;
    padding-bottom: 24px;
    border-bottom: 1px solid var(--gray-150);

    .avatar-container {
      display: inline-block;

      .avatar-display {
        margin-bottom: 16px;

        .large-avatar {
          width: 80px;
          height: 80px;
          border-radius: 50%;
          object-fit: cover;
          border: 3px solid var(--gray-150);
          box-shadow: 0 2px 8px var(--shadow-2);
        }

        .default-avatar {
          width: 80px;
          height: 80px;
          border-radius: 50%;
          background: var(--gray-50);
          display: flex;
          margin: 0 auto;
          align-items: center;
          justify-content: center;
          border: 3px solid var(--gray-150);
          box-shadow: 0 2px 8px var(--shadow-2);

          // Keep icon centered
          :deep(svg) {
            color: var(--gray-400);
          }
        }
      }

      .avatar-actions {
        .avatar-tips {
          margin-top: 8px;
          font-size: 12px;
          color: var(--gray-500);
          line-height: 1.4;
        }
      }
    }
  }

  .info-section {
    margin-bottom: 24px;

    .info-item {
      display: flex;
      align-items: center;
      padding: 12px;
      border-bottom: 1px solid var(--gray-50);

      &:last-child {
        border-bottom: none;
      }

      .info-label {
        width: 120px;
        font-weight: 500;
        color: var(--gray-600);
        flex-shrink: 0;
      }

      .info-value {
        flex: 1;
        color: var(--gray-900);
        font-size: 14px;

        &.user-id {
          font-family: 'Monaco', 'Consolas', monospace;
          // background: var(--gray-50);
          // padding: 4px 8px;
          border-radius: 4px;
          display: inline-block;
        }
      }
    }
  }

  .actions-section {
    text-align: center;
    padding-top: 16px;
    border-top: 1px solid var(--gray-150);
  }
}

:deep(.ant-dropdown-menu) {
  padding: 8px 0;
}

:deep(.ant-dropdown-menu-title-content) {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--gray-900);
}

:deep(.ant-dropdown-menu-item svg) {
  margin-right: 4px;
  color: var(--gray-900);
  vertical-align: middle;
}

.menu-text {
  line-height: 20px;
}
</style>
