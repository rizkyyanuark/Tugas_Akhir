<template>
  <div class="user-management">
    <!-- Header section -->
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">User Management</div>
        <p class="section-description">
          Manage system users carefully. Deleted users will no longer be able to sign in.
        </p>
      </div>
      <a-button type="primary" @click="showAddUserModal" class="add-btn lucide-icon-btn">
        <template #icon><Plus :size="16" /></template>
        Add User
      </a-button>
    </div>

    <!-- Main content section -->
    <div class="content-section">
      <a-spin :spinning="userManagement.loading">
        <div v-if="userManagement.error" class="error-message">
          <a-alert type="error" :message="userManagement.error" show-icon />
        </div>

        <div class="cards-container">
          <div v-if="userManagement.users.length === 0" class="empty-state">
            <a-empty description="No user data" />
          </div>
          <div v-else class="user-cards-grid">
            <div v-for="user in userManagement.users" :key="user.id" class="user-card">
              <div class="card-header">
                <div class="user-info-main">
                  <div class="user-avatar">
                    <img
                      v-if="user.avatar"
                      :src="user.avatar"
                      :alt="user.username"
                      class="avatar-img"
                    />
                    <div v-else class="avatar-placeholder">
                      {{ user.username.charAt(0).toUpperCase() }}
                    </div>
                  </div>
                  <div class="user-info-content">
                    <div class="name-tag-row">
                      <h4 class="username">{{ user.username }}</h4>
                      <div
                        v-if="
                          user.role === 'admin' ||
                          user.role === 'superadmin' ||
                          user.department_name
                        "
                        class="role-dept-badge"
                      >
                        <span class="role-icon-wrapper" :class="getRoleClass(user.role)">
                          <UserLock v-if="user.role === 'superadmin'" :size="14" />
                          <UserStar v-else-if="user.role === 'admin'" :size="14" />
                          <User v-else :size="14" />
                        </span>
                        <span v-if="user.department_name" class="dept-text">
                          {{ user.department_name }}
                        </span>
                      </div>
                    </div>
                    <div class="user-id-row">ID: {{ user.user_id || '-' }}</div>
                  </div>
                </div>
              </div>

              <div class="card-content">
                <div class="info-item">
                  <span class="info-label">Phone:</span>
                  <span class="info-value phone-text">{{ user.phone_number || '-' }}</span>
                </div>
                <div class="info-item">
                  <span class="info-label">Created At:</span>
                  <span class="info-value time-text">{{ formatTime(user.created_at) }}</span>
                </div>
                <div class="info-item">
                  <span class="info-label">Last Login:</span>
                  <span class="info-value time-text">{{ formatTime(user.last_login) }}</span>
                </div>
              </div>

              <div class="card-actions">
                <a-tooltip title="Edit user">
                  <a-button
                    type="text"
                    size="small"
                    @click="showEditUserModal(user)"
                    class="action-btn lucide-icon-btn"
                  >
                    <Pencil :size="14" />
                    <span>Edit</span>
                  </a-button>
                </a-tooltip>
                <a-tooltip title="Delete user">
                  <a-button
                    type="text"
                    size="small"
                    danger
                    @click="confirmDeleteUser(user)"
                    :disabled="
                      user.id === userStore.userId ||
                      (user.role === 'superadmin' && userStore.userRole !== 'superadmin')
                    "
                    class="action-btn lucide-icon-btn"
                  >
                    <Trash2 :size="14" />
                    <span>Delete</span>
                  </a-button>
                </a-tooltip>
              </div>
            </div>
          </div>
        </div>
      </a-spin>
    </div>

    <!-- User form modal -->
    <a-modal
      v-model:open="userManagement.modalVisible"
      :title="userManagement.modalTitle"
      @ok="handleUserFormSubmit"
      :confirmLoading="userManagement.loading"
      @cancel="userManagement.modalVisible = false"
      :maskClosable="false"
      width="480px"
      class="user-modal"
    >
      <a-form layout="vertical" class="user-form">
        <a-form-item label="Username" required class="form-item">
          <a-input
            v-model:value="userManagement.form.username"
            placeholder="Enter username (2-20 characters)"
            size="large"
            @blur="validateAndGenerateUserId"
            :maxlength="20"
          />
          <div v-if="userManagement.form.usernameError" class="error-text">
            {{ userManagement.form.usernameError }}
          </div>
        </a-form-item>

        <!-- Display auto-generated user ID -->
        <a-form-item
          v-if="userManagement.form.generatedUserId || userManagement.editMode"
          label="User ID"
          class="form-item"
        >
          <a-input
            :value="userManagement.form.generatedUserId"
            placeholder="Auto-generated"
            size="large"
            disabled
            :addon-before="userManagement.editMode ? 'Existing ID' : 'Login ID'"
          />
          <div v-if="!userManagement.editMode" class="help-text">
            This ID is used for login and auto-generated from username
          </div>
          <div v-else class="help-text">User ID cannot be modified in edit mode</div>
        </a-form-item>

        <!-- Phone number field -->
        <a-form-item label="Phone Number" class="form-item">
          <a-input
            v-model:value="userManagement.form.phoneNumber"
            placeholder="Enter phone number (optional, can be used for login)"
            size="large"
            :maxlength="11"
          />
          <div v-if="userManagement.form.phoneError" class="error-text">
            {{ userManagement.form.phoneError }}
          </div>
        </a-form-item>

        <template v-if="userManagement.editMode">
          <div class="password-toggle">
            <a-checkbox v-model:checked="userManagement.displayPasswordFields">
              Change Password
            </a-checkbox>
          </div>
        </template>

        <template v-if="!userManagement.editMode || userManagement.displayPasswordFields">
          <a-form-item label="Password" required class="form-item">
            <a-input-password
              v-model:value="userManagement.form.password"
              placeholder="Enter password"
              size="large"
            />
          </a-form-item>

          <a-form-item label="Confirm Password" required class="form-item">
            <a-input-password
              v-model:value="userManagement.form.confirmPassword"
              placeholder="Re-enter password"
              size="large"
            />
          </a-form-item>
        </template>

        <a-form-item
          v-if="userManagement.editMode && userManagement.form.role === 'superadmin'"
          label="Role"
          class="form-item"
        >
          <a-input value="Super Admin" size="large" disabled />
          <div class="help-text">Super admin role cannot be changed</div>
        </a-form-item>
        <a-form-item v-else label="Role" class="form-item">
          <a-select v-model:value="userManagement.form.role" size="large">
            <a-select-option value="user">User</a-select-option>
            <a-select-option value="admin" v-if="userStore.isSuperAdmin">Admin</a-select-option>
          </a-select>
        </a-form-item>

        <!-- Department selector (Super Admin only) -->
        <a-form-item v-if="userStore.isSuperAdmin" label="Department" class="form-item">
          <a-select
            v-model:value="userManagement.form.departmentId"
            size="large"
            placeholder="Select a department"
          >
            <a-select-option
              v-for="dept in departmentManagement.departments"
              :key="dept.id"
              :value="dept.id"
            >
              {{ dept.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { reactive, onMounted, watch } from 'vue'
import { notification, Modal } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'
import { departmentApi } from '@/apis'
import { Plus, Pencil, Trash2, User, UserLock, UserStar } from 'lucide-vue-next'
import { formatDateTime } from '@/utils/time'

const userStore = useUserStore()

// User management state
const userManagement = reactive({
  loading: false,
  users: [],
  error: null,
  modalVisible: false,
  modalTitle: 'Add User',
  editMode: false,
  editUserId: null,
  form: {
    username: '',
    generatedUserId: '', // auto-generated user_id
    phoneNumber: '', // phone number
    password: '',
    confirmPassword: '',
    role: 'user', // default role
    departmentId: null, // department ID
    usernameError: '', // username error message
    phoneError: '' // phone number error message
  },
  displayPasswordFields: true // whether to show password fields in edit mode
})

// Department list (Super Admin only)
const departmentManagement = reactive({
  departments: []
})

// Fetch department list
const fetchDepartments = async () => {
  if (!userStore.isSuperAdmin) return // Non-super admins do not need all departments
  try {
    const departments = await departmentApi.getDepartments()
    departmentManagement.departments = departments
  } catch (error) {
    console.error('Failed to fetch department list:', error)
  }
}

// Validate username and generate user_id
const validateAndGenerateUserId = async () => {
  const username = userManagement.form.username.trim()

  // Clear previous errors and generated ID
  userManagement.form.usernameError = ''
  userManagement.form.generatedUserId = ''

  if (!username) {
    return
  }

  // No need to regenerate user_id in edit mode
  if (userManagement.editMode) {
    return
  }

  try {
    const result = await userStore.validateUsernameAndGenerateUserId(username)
    userManagement.form.generatedUserId = result.user_id
  } catch (error) {
    userManagement.form.usernameError = error.message || 'Username validation failed'
  }
}

// Validate phone number format
const validatePhoneNumber = (phone) => {
  if (!phone) {
    return true // phone number is optional
  }

  // Indonesian mobile phone format validation
  const phoneRegex = /^(?:\+62|62|0)8[1-9][0-9]{7,10}$/
  return phoneRegex.test(phone)
}

// Watch password field visibility changes
watch(
  () => userManagement.displayPasswordFields,
  (newVal) => {
    // Clear password inputs when hiding password fields
    if (!newVal) {
      userManagement.form.password = ''
      userManagement.form.confirmPassword = ''
    }
  }
)

// Watch phone number input changes
watch(
  () => userManagement.form.phoneNumber,
  (newPhone) => {
    userManagement.form.phoneError = ''

    if (newPhone && !validatePhoneNumber(newPhone)) {
      userManagement.form.phoneError =
        'Please enter a valid Indonesian phone number (e.g. 089..., 628..., or +628...)'
    }
  }
)

// Format time display
const formatTime = (timeStr) => formatDateTime(timeStr)

// Fetch user list
const fetchUsers = async () => {
  try {
    userManagement.loading = true
    const users = await userStore.getUsers()
    userManagement.users = users
    userManagement.error = null
  } catch (error) {
    console.error('Failed to fetch user list:', error)
    userManagement.error = 'Failed to fetch user list'
  } finally {
    userManagement.loading = false
  }
}

// Open add user modal
const showAddUserModal = () => {
  userManagement.modalTitle = 'Add User'
  userManagement.editMode = false
  userManagement.editUserId = null
  userManagement.form = {
    username: '',
    generatedUserId: '',
    phoneNumber: '',
    password: '',
    confirmPassword: '',
    role: 'user', // default role is user
    departmentId: null,
    usernameError: '',
    phoneError: ''
  }
  userManagement.displayPasswordFields = true
  userManagement.modalVisible = true
}

// Open edit user modal
const showEditUserModal = (user) => {
  userManagement.modalTitle = 'Edit User'
  userManagement.editMode = true
  userManagement.editUserId = user.id
  userManagement.form = {
    username: user.username,
    generatedUserId: user.user_id || '', // show existing user_id in edit mode
    phoneNumber: user.phone_number || '',
    password: '',
    confirmPassword: '',
    role: user.role,
    departmentId: user.department_id || null,
    usernameError: '',
    phoneError: ''
  }
  userManagement.displayPasswordFields = false // hide password fields by default
  userManagement.modalVisible = true
}

// Handle user form submit
const handleUserFormSubmit = async () => {
  try {
    // Basic validation
    if (!userManagement.form.username.trim()) {
      notification.error({ message: 'Username cannot be empty' })
      return
    }

    // Validate username length
    if (
      userManagement.form.username.trim().length < 2 ||
      userManagement.form.username.trim().length > 20
    ) {
      notification.error({ message: 'Username length must be between 2 and 20 characters' })
      return
    }

    // Validate phone number
    if (userManagement.form.phoneNumber && !validatePhoneNumber(userManagement.form.phoneNumber)) {
      notification.error({
        message: 'Please enter a valid Indonesian phone number (e.g. 089..., 628..., or +628...)'
      })
      return
    }

    if (userManagement.displayPasswordFields) {
      if (!userManagement.form.password) {
        notification.error({ message: 'Password cannot be empty' })
        return
      }

      if (userManagement.form.password !== userManagement.form.confirmPassword) {
        notification.error({ message: 'The two passwords do not match' })
        return
      }
    }

    userManagement.loading = true

    // Create or update user based on mode
    if (userManagement.editMode) {
      // Build update payload
      const updateData = {
        username: userManagement.form.username.trim(),
        role: userManagement.form.role
      }

      // Add phone number field
      if (userManagement.form.phoneNumber) {
        updateData.phone_number = userManagement.form.phoneNumber
      }

      // Super admin can update department
      if (userStore.isSuperAdmin && userManagement.form.departmentId) {
        updateData.department_id = userManagement.form.departmentId
      }

      // Update password only when password fields are visible and filled
      if (userManagement.displayPasswordFields && userManagement.form.password) {
        updateData.password = userManagement.form.password
      }

      await userStore.updateUser(userManagement.editUserId, updateData)
      notification.success({ message: 'User updated successfully' })
    } else {
      // Create new user
      const createData = {
        username: userManagement.form.username.trim(),
        password: userManagement.form.password,
        role: userManagement.form.role
      }

      // Super admin can assign department
      if (userStore.isSuperAdmin && userManagement.form.departmentId) {
        createData.department_id = userManagement.form.departmentId
      }

      // Add phone number field when provided
      if (userManagement.form.phoneNumber) {
        createData.phone_number = userManagement.form.phoneNumber
      }

      await userStore.createUser(createData)
      notification.success({ message: 'User created successfully' })
    }

    // Refresh user list
    await fetchUsers()
    userManagement.modalVisible = false
  } catch (error) {
    console.error('User operation failed:', error)
    notification.error({
      message: 'Operation failed',
      description: error.message || 'Please try again later'
    })
  } finally {
    userManagement.loading = false
  }
}

// Delete user
const confirmDeleteUser = (user) => {
  // Users cannot delete themselves
  if (user.id === userStore.userId) {
    notification.error({ message: 'You cannot delete your own account' })
    return
  }

  // Confirmation dialog
  Modal.confirm({
    title: 'Confirm User Deletion',
    content: `Are you sure you want to delete user "${user.username}"? This action cannot be undone.`,
    okText: 'Delete',
    okType: 'danger',
    cancelText: 'Cancel',
    async onOk() {
      try {
        userManagement.loading = true
        await userStore.deleteUser(user.id)
        notification.success({ message: 'User deleted successfully' })
        // Refresh user list
        await fetchUsers()
      } catch (error) {
        console.error('Failed to delete user:', error)
        notification.error({
          message: 'Deletion failed',
          description: error.message || 'Please try again later'
        })
      } finally {
        userManagement.loading = false
      }
    }
  })
}

const getRoleClass = (role) => {
  switch (role) {
    case 'superadmin':
      return 'role-superadmin'
    case 'admin':
      return 'role-admin'
    case 'user':
      return 'role-user'
    default:
      return 'role-default'
  }
}

// Fetch user list on component mount
onMounted(async () => {
  await fetchUsers()
  await fetchDepartments()
})
</script>

<style lang="less" scoped>
.user-management {
  .content-section {
    overflow: hidden;

    .error-message {
      padding: 16px 24px;
    }

    .cards-container {
      .empty-state {
        padding: 60px 20px;
        text-align: center;
      }

      .user-cards-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 16px;
        // padding: 16px;

        .user-card {
          background: var(--gray-0);
          border: 1px solid var(--gray-150);
          border-radius: 8px;
          padding: 12px;
          padding-bottom: 6px;

          transition: all 0.2s ease;
          box-shadow: 0 1px 3px var(--shadow-1);

          &:hover {
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            border-color: var(--gray-200);
          }

          .card-header {
            margin-bottom: 10px;

            .user-info-main {
              display: flex;
              gap: 12px;
              align-items: center;

              .user-avatar {
                width: 40px;
                height: 40px;
                border-radius: 50%;
                background: var(--gray-50);
                display: flex;
                align-items: center;
                justify-content: center;
                overflow: hidden;
                flex-shrink: 0;

                .avatar-img {
                  width: 100%;
                  height: 100%;
                  object-fit: cover;
                }

                .avatar-placeholder {
                  color: var(--gray-600);
                  font-weight: 500;
                  font-size: 14px;
                }
              }

              .user-info-content {
                flex: 1;
                min-width: 0;

                .name-tag-row {
                  display: flex;
                  align-items: center;
                  justify-content: space-between;
                  gap: 8px;
                  margin-bottom: 2px;
                  flex-wrap: wrap;

                  .username {
                    margin: 0;
                    font-size: 15px;
                    font-weight: 600;
                    color: var(--gray-900);
                    line-height: 1.2;
                    flex-shrink: 0;
                  }

                  .role-dept-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 4px;
                    padding: 2px 8px 2px 4px;
                    background: var(--gray-50);
                    border-radius: 4px;

                    .role-icon-wrapper {
                      display: flex;
                      align-items: center;
                      justify-content: center;
                      width: 16px;
                      height: 16px;

                      &.role-superadmin {
                        color: var(--color-error-700);
                      }
                      &.role-admin {
                        color: var(--color-info-700);
                      }
                      &.role-user {
                        color: var(--color-success-700);
                      }
                    }

                    .dept-text {
                      font-size: 12px;
                      color: var(--gray-700);
                      font-weight: 500;
                    }
                  }
                }

                .user-id-row {
                  font-size: 12px;
                  color: var(--gray-500);
                  font-family: 'Monaco', 'Consolas', monospace;
                  line-height: 1.2;
                }
              }
            }
          }

          .card-content {
            .info-item {
              display: flex;
              justify-content: space-between;
              align-items: center;
              padding: 2px 0;
              border-bottom: 1px solid var(--gray-25);

              &:last-child {
                border-bottom: none;
              }

              .info-label {
                font-size: 12px;
                color: var(--gray-600);
                font-weight: 500;
                min-width: 70px;
              }

              .info-value {
                font-size: 12px;
                color: var(--gray-900);
                text-align: right;
                flex: 1;

                &.time-text {
                  color: var(--gray-700);
                }

                &.phone-text {
                  font-family: 'Monaco', 'Consolas', monospace;
                }
              }
            }
          }

          .card-actions {
            display: flex;
            justify-content: flex-end;
            gap: 6px;
            padding-top: 6px;
            border-top: 1px solid var(--gray-25);

            .action-btn {
              display: flex;
              align-items: center;
              gap: 4px;
              padding: 4px 8px;
              border-radius: 6px;
              transition: all 0.2s ease;
              font-size: 12px;

              span {
                font-size: 12px;
              }

              &:hover {
                background: var(--gray-25);
              }

              &.ant-btn-dangerous:hover {
                background: var(--gray-25);
                border-color: var(--color-error-500);
                color: var(--color-error-500);
              }
            }
          }
        }
      }
    }
  }

  .time-text {
    font-size: 13px;
    color: var(--gray-700);
  }

  .phone-text,
  .user-id-text {
    font-size: 13px;
    color: var(--gray-900);
    font-family: 'Monaco', 'Consolas', monospace;
  }
}

.user-modal {
  :deep(.ant-modal-header) {
    padding: 20px 24px;
    border-bottom: 1px solid var(--gray-150);

    .ant-modal-title {
      font-size: 16px;
      font-weight: 600;
      color: var(--gray-900);
    }
  }

  :deep(.ant-modal-body) {
    padding: 24px;
  }

  .user-form {
    .form-item {
      margin-bottom: 20px;

      :deep(.ant-form-item-label) {
        padding-bottom: 4px;

        label {
          font-weight: 500;
          color: var(--gray-900);
        }
      }
    }

    .error-text {
      color: var(--color-error-500);
      font-size: 12px;
      margin-top: 4px;
      line-height: 1.3;
    }

    .help-text {
      color: var(--gray-600);
      font-size: 12px;
      margin-top: 4px;
      line-height: 1.3;
    }

    .password-toggle {
      margin-bottom: 16px;

      :deep(.ant-checkbox-wrapper) {
        font-weight: 500;
        color: var(--gray-600);
      }
    }
  }
}
</style>
