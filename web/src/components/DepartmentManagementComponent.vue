<template>
  <div class="department-management">
    <!-- Header section -->
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">Department Management</div>
        <p class="section-description">
          Manage system departments. Users in each department are isolated.
        </p>
      </div>
      <a-button type="primary" @click="showAddDepartmentModal" class="add-btn lucide-icon-btn">
        <template #icon><Plus :size="16" /></template>
        Add Department
      </a-button>
    </div>

    <!-- Main content section -->
    <div class="content-section">
      <a-spin :spinning="departmentManagement.loading">
        <div v-if="departmentManagement.error" class="error-message">
          <a-alert type="error" :message="departmentManagement.error" show-icon />
        </div>

        <template v-if="departmentManagement.departments.length > 0">
          <a-table
            :dataSource="departmentManagement.departments"
            :columns="columns"
            :rowKey="(record) => record.id"
            :pagination="false"
            class="department-table"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <div class="department-name">
                  <span class="name-text">{{ record.name }}</span>
                </div>
              </template>
              <template v-if="column.key === 'description'">
                <span class="description-text">{{ record.description || '-' }}</span>
              </template>
              <template v-if="column.key === 'userCount'">
                <span>{{ record.user_count ?? 0 }} users</span>
              </template>
              <template v-if="column.key === 'action'">
                <a-space>
                  <a-tooltip title="Edit Department">
                    <a-button
                      type="text"
                      size="small"
                      @click="showEditDepartmentModal(record)"
                      class="action-btn lucide-icon-btn"
                    >
                      <Pencil :size="14" />
                    </a-button>
                  </a-tooltip>
                  <a-tooltip title="Delete Department">
                    <a-button
                      type="text"
                      size="small"
                      danger
                      @click="confirmDeleteDepartment(record)"
                      :disabled="record.id === 1"
                      class="action-btn lucide-icon-btn"
                    >
                      <Trash2 :size="14" />
                    </a-button>
                  </a-tooltip>
                </a-space>
              </template>
            </template>
          </a-table>
        </template>

        <div v-else class="empty-state">
          <a-empty description="No department data" />
        </div>
      </a-spin>
    </div>

    <!-- Department form modal -->
    <a-modal
      v-model:open="departmentManagement.modalVisible"
      :title="departmentManagement.modalTitle"
      @ok="handleDepartmentFormSubmit"
      :confirmLoading="departmentManagement.loading"
      @cancel="departmentManagement.modalVisible = false"
      :maskClosable="false"
      width="520px"
      class="department-modal"
    >
      <a-form layout="vertical" class="department-form">
        <a-form-item label="Department Name" required class="form-item">
          <a-input
            v-model:value="departmentManagement.form.name"
            placeholder="Please enter a department name"
            size="large"
            :maxlength="50"
          />
        </a-form-item>

        <a-form-item label="Department Description" class="form-item">
          <a-textarea
            v-model:value="departmentManagement.form.description"
            placeholder="Please enter a department description (optional)"
            :rows="3"
            :maxlength="255"
            show-count
          />
        </a-form-item>

        <a-divider v-if="!departmentManagement.editMode" />

        <template v-if="!departmentManagement.editMode">
          <div class="admin-section-title">
            <Users :size="16" />
            <span>Department Admin</span>
          </div>
          <p class="admin-section-hint">
            Creating a department requires creating an admin at the same time. This admin will
            manage users in this department.
          </p>

          <a-form-item label="Admin User ID" required class="form-item">
            <a-input
              v-model:value="departmentManagement.form.adminUserId"
              placeholder="Enter admin user ID (3-20 letters/numbers/underscores)"
              size="large"
              :maxlength="20"
              @blur="checkAdminUserId"
            />
            <div v-if="departmentManagement.form.userIdError" class="error-text">
              {{ departmentManagement.form.userIdError }}
            </div>
            <div v-else class="help-text">This ID will be used for login</div>
          </a-form-item>

          <a-form-item label="Password" required class="form-item">
            <a-input-password
              v-model:value="departmentManagement.form.adminPassword"
              placeholder="Enter admin password"
              size="large"
              :maxlength="50"
            />
          </a-form-item>

          <a-form-item label="Confirm Password" required class="form-item">
            <a-input-password
              v-model:value="departmentManagement.form.adminConfirmPassword"
              placeholder="Please re-enter password"
              size="large"
              :maxlength="50"
            />
          </a-form-item>

          <a-form-item label="Phone Number (optional)" class="form-item">
            <a-input
              v-model:value="departmentManagement.form.adminPhone"
              placeholder="Enter phone number (can be used for login)"
              size="large"
              :maxlength="11"
            />
            <div v-if="departmentManagement.form.phoneError" class="error-text">
              {{ departmentManagement.form.phoneError }}
            </div>
          </a-form-item>
        </template>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { reactive, onMounted, watch } from 'vue'
import { notification, Modal } from 'ant-design-vue'
import { departmentApi, apiSuperAdminGet } from '@/apis'
import { Delete as Trash2, Edit3 as Pencil, Plus, Users } from 'lucide-vue-next'

// Table column definitions
const columns = [
  {
    title: 'Department Name',
    dataIndex: 'name',
    key: 'name',
    width: 200
  },
  {
    title: 'Description',
    dataIndex: 'description',
    key: 'description',
    ellipsis: true
  },
  {
    title: 'User Count',
    dataIndex: 'user_count',
    key: 'userCount',
    width: 100,
    align: 'center'
  },
  {
    title: 'Actions',
    key: 'action',
    width: 120,
    align: 'center'
  }
]

// Department management state
const departmentManagement = reactive({
  loading: false,
  departments: [],
  error: null,
  modalVisible: false,
  modalTitle: 'Add Department',
  editMode: false,
  editDepartmentId: null,
  form: {
    name: '',
    description: '',
    adminUserId: '',
    adminPassword: '',
    adminConfirmPassword: '',
    adminPhone: '',
    userIdError: '',
    phoneError: ''
  }
})

// Fetch department list
const fetchDepartments = async () => {
  try {
    departmentManagement.loading = true
    departmentManagement.error = null
    const departments = await departmentApi.getDepartments()
    departmentManagement.departments = departments
  } catch (error) {
    console.error('Failed to fetch department list:', error)
    departmentManagement.error = 'Failed to fetch department list'
  } finally {
    departmentManagement.loading = false
  }
}

// Open add department modal
const showAddDepartmentModal = () => {
  departmentManagement.modalTitle = 'Add Department'
  departmentManagement.editMode = false
  departmentManagement.editDepartmentId = null
  departmentManagement.form = {
    name: '',
    description: '',
    adminUserId: '',
    adminPassword: '',
    adminConfirmPassword: '',
    adminPhone: '',
    userIdError: '',
    phoneError: ''
  }
  departmentManagement.modalVisible = true
}

// Open edit department modal
const showEditDepartmentModal = (department) => {
  departmentManagement.modalTitle = 'Edit Department'
  departmentManagement.editMode = true
  departmentManagement.editDepartmentId = department.id
  departmentManagement.form = {
    name: department.name,
    description: department.description || '',
    adminUserId: '',
    adminPassword: '',
    adminConfirmPassword: '',
    adminPhone: '',
    userIdError: '',
    phoneError: ''
  }
  departmentManagement.modalVisible = true
}

// Validate phone number format
const validatePhoneNumber = (phone) => {
  if (!phone) {
    return true // Phone number is optional
  }
  const phoneRegex = /^(?:\+62|62|0)8[1-9][0-9]{7,10}$/
  return phoneRegex.test(phone)
}

// Watch phone number input changes
watch(
  () => departmentManagement.form.adminPhone,
  (newPhone) => {
    departmentManagement.form.phoneError = ''
    if (newPhone && !validatePhoneNumber(newPhone)) {
      departmentManagement.form.phoneError =
        'Please enter a valid Indonesian phone number (e.g. 089..., 628..., or +628...)'
    }
  }
)

// Check if admin user ID is available
const checkAdminUserId = async () => {
  const userId = departmentManagement.form.adminUserId.trim()
  departmentManagement.form.userIdError = ''

  if (!userId) {
    return
  }

  // Validate format
  if (!/^[a-zA-Z0-9_]+$/.test(userId)) {
    departmentManagement.form.userIdError =
      'User ID can only contain letters, numbers, and underscores'
    return
  }

  if (userId.length < 3 || userId.length > 20) {
    departmentManagement.form.userIdError = 'User ID length must be between 3 and 20 characters'
    return
  }

  // Check whether it already exists
  try {
    const result = await apiSuperAdminGet(`/api/auth/check-user-id/${userId}`)
    if (!result.is_available) {
      departmentManagement.form.userIdError = 'This user ID is already in use'
    }
  } catch (error) {
    console.error('Failed to check user ID:', error)
  }
}

// Handle department form submission
const handleDepartmentFormSubmit = async () => {
  try {
    // Validate department name
    if (!departmentManagement.form.name.trim()) {
      notification.error({ message: 'Department name cannot be empty' })
      return
    }

    if (departmentManagement.form.name.trim().length < 2) {
      notification.error({ message: 'Department name must be at least 2 characters' })
      return
    }

    const adminUserId = departmentManagement.form.adminUserId.trim()

    // Admin account fields are required only when creating a department.
    if (!departmentManagement.editMode) {
      // Validate admin user ID
      if (!adminUserId) {
        notification.error({ message: 'Please enter admin user ID' })
        return
      }

      if (!/^[a-zA-Z0-9_]+$/.test(adminUserId)) {
        notification.error({
          message: 'User ID can only contain letters, numbers, and underscores'
        })
        return
      }

      if (adminUserId.length < 3 || adminUserId.length > 20) {
        notification.error({ message: 'User ID length must be between 3 and 20 characters' })
        return
      }

      if (departmentManagement.form.userIdError) {
        notification.error({ message: 'Admin user ID already exists or format is invalid' })
        return
      }

      // Validate password
      if (!departmentManagement.form.adminPassword) {
        notification.error({ message: 'Please enter admin password' })
        return
      }

      if (
        departmentManagement.form.adminPassword !== departmentManagement.form.adminConfirmPassword
      ) {
        notification.error({ message: 'The two passwords do not match' })
        return
      }

      // Validate phone number
      if (
        departmentManagement.form.adminPhone &&
        !validatePhoneNumber(departmentManagement.form.adminPhone)
      ) {
        notification.error({
          message: 'Please enter a valid Indonesian phone number (e.g. 089..., 628..., or +628...)'
        })
        return
      }
    }

    departmentManagement.loading = true

    if (departmentManagement.editMode) {
      // Update department
      await departmentApi.updateDepartment(departmentManagement.editDepartmentId, {
        name: departmentManagement.form.name.trim(),
        description: departmentManagement.form.description.trim() || undefined
      })
      notification.success({ message: 'Department updated successfully' })
    } else {
      // Create department and admin at the same time
      await departmentApi.createDepartment({
        name: departmentManagement.form.name.trim(),
        description: departmentManagement.form.description.trim() || undefined,
        admin_user_id: adminUserId,
        admin_password: departmentManagement.form.adminPassword,
        admin_phone: departmentManagement.form.adminPhone || undefined
      })

      notification.success({
        message: `Department created successfully, admin "${adminUserId}" has been created`
      })
    }

    // Refresh department list
    await fetchDepartments()
    departmentManagement.modalVisible = false
  } catch (error) {
    console.error('Department operation failed:', error)
    notification.error({
      message: 'Operation failed',
      description: error.message || 'Please try again later'
    })
  } finally {
    departmentManagement.loading = false
  }
}

// Delete department
const confirmDeleteDepartment = (department) => {
  Modal.confirm({
    title: 'Confirm Department Deletion',
    content: `Are you sure you want to delete department "${department.name}"? This action cannot be undone. Users in this department will be migrated to the default department, and department-level settings and API keys will be cleaned up.`,
    okText: 'Delete',
    okType: 'danger',
    cancelText: 'Cancel',
    async onOk() {
      try {
        departmentManagement.loading = true
        await departmentApi.deleteDepartment(department.id)
        notification.success({ message: 'Department deleted successfully' })
        // Refresh department list
        await fetchDepartments()
      } catch (error) {
        console.error('Failed to delete department:', error)
        notification.error({
          message: 'Deletion failed',
          description: error.message || 'Please try again later'
        })
      } finally {
        departmentManagement.loading = false
      }
    }
  })
}

// Fetch department list on component mount
onMounted(() => {
  fetchDepartments()
})
</script>

<style lang="less" scoped>
.department-management {
  .content-section {
    overflow: hidden;

    .error-message {
      padding: 16px 24px;
    }

    .empty-state {
      padding: 60px 20px;
      text-align: center;
    }

    .department-table {
      :deep(.ant-table-thead > tr > th) {
        background: var(--gray-50);
        font-weight: 500;
        padding: 8px 12px;
      }

      :deep(.ant-table-tbody > tr > td) {
        padding: 8px 12px;
      }

      .department-name {
        .name-text {
          font-weight: 500;
          color: var(--gray-900);
        }
      }

      .description-text {
        color: var(--gray-600);
      }

      .action-btn {
        padding: 4px 8px;
        border-radius: 6px;
        transition: all 0.2s ease;

        &:hover {
          background: var(--gray-25);
        }
      }
    }
  }
}

.department-modal {
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

  .department-form {
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
}
</style>
