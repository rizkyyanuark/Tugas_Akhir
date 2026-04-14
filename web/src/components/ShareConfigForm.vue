<template>
  <div class="share-config-form">
    <div class="share-config-content">
      <div class="share-mode">
        <a-radio-group v-model:value="config.is_shared" class="share-mode-radio">
          <a-radio :value="true">Share with All</a-radio>
          <a-radio :value="false">Specific Departments</a-radio>
        </a-radio-group>
      </div>
      <p class="share-hint">
        {{ config.is_shared ? 'Accessible to all users' : 'Only selected departments can access' }}
      </p>
      <!-- Department selection -->
      <div v-if="!config.is_shared" class="dept-selection">
        <a-select
          v-model:value="config.accessible_department_ids"
          mode="multiple"
          placeholder="Select accessible departments"
          style="width: 100%"
          :options="departmentOptions"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useUserStore } from '@/stores/user'
import { departmentApi } from '@/apis/department_api'

const userStore = useUserStore()
const departments = ref([])

const props = defineProps({
  modelValue: {
    type: Object,
    required: true,
    default: () => ({
      is_shared: true,
      accessible_department_ids: []
    })
  },
  // Whether to auto-select the current user's department
  autoSelectUserDept: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue'])

// Local state initialized from props
const config = reactive({
  is_shared: true,
  accessible_department_ids: []
})

// Initialize config
const initConfig = () => {
  // Backend returns accessible_departments; frontend uses accessible_department_ids
  const sourceDepts =
    props.modelValue.accessible_department_ids ?? props.modelValue.accessible_departments ?? []
  config.is_shared = props.modelValue.is_shared ?? true
  config.accessible_department_ids = sourceDepts.map((id) => Number(id))
  console.log('[ShareConfigForm] initConfig:', JSON.stringify(config))
}

// Initialize once on mount
onMounted(() => {
  initConfig()
})

// Sync local config changes to parent
watch(
  config,
  (newVal) => {
    console.log('[ShareConfigForm] config changed, emit:', JSON.stringify(newVal))
    emit('update:modelValue', {
      is_shared: newVal.is_shared,
      accessible_department_ids: newVal.accessible_department_ids
    })
  },
  { deep: true }
)

// Watch share mode changes
watch(
  () => config.is_shared,
  (newVal) => {
    if (!newVal && props.autoSelectUserDept && config.accessible_department_ids.length === 0) {
      // In specific-department mode, auto-select current user's department when none selected
      tryAutoSelectUserDept()
    }
  }
)

// Try auto-selecting the user's department
const tryAutoSelectUserDept = () => {
  const userDeptId = userStore.departmentId
  if (userDeptId) {
    const deptExists = departments.value.find((d) => d.id === userDeptId)
    if (deptExists) {
      // Ensure numeric type (a-select may return strings)
      config.accessible_department_ids = [Number(userDeptId)]
    }
  }
}

// Watch user department changes (departmentId may become available after mount)
watch(
  () => userStore.departmentId,
  (newDeptId) => {
    if (
      props.autoSelectUserDept &&
      !config.is_shared &&
      config.accessible_department_ids.length === 0 &&
      newDeptId
    ) {
      tryAutoSelectUserDept()
    }
  }
)

// Department options
const departmentOptions = computed(() =>
  departments.value.map((dept) => ({
    label: dept.name,
    value: Number(dept.id)
  }))
)

// Load department list
const loadDepartments = async () => {
  try {
    const res = await departmentApi.getDepartments()
    departments.value = res.departments || res || []

    // Auto-select current user department if needed
    if (
      props.autoSelectUserDept &&
      !config.is_shared &&
      config.accessible_department_ids.length === 0
    ) {
      tryAutoSelectUserDept()
    }
  } catch (e) {
    console.error('Failed to load department list:', e)
    departments.value = []
  }
}

onMounted(() => {
  loadDepartments()
})

// Validate whether the current user's department is included in accessible departments
// Returns { valid: boolean, message: string }
const validate = () => {
  // No validation required in share-with-all mode
  if (config.is_shared) {
    return { valid: true, message: '' }
  }

  // In specific-department mode, ensure current user's department is included
  const userDeptId = userStore.departmentId
  if (!userDeptId) {
    return {
      valid: false,
      message:
        'You are not assigned to any department and cannot use specific department sharing mode'
    }
  }

  if (!config.accessible_department_ids.includes(userDeptId)) {
    return {
      valid: false,
      message: 'Your department must be included in accessible departments'
    }
  }

  return { valid: true, message: '' }
}

// Expose methods to parent component
defineExpose({
  config,
  validate
})
</script>

<style lang="less" scoped>
.share-config-form {
  h3 {
    margin-top: 20px;
    margin-bottom: 12px;
  }

  .share-config-content {
    background: var(--gray-25);
    border-radius: 8px;
    padding: 16px;
    border: 1px solid var(--gray-150);

    .share-mode {
      .share-mode-radio {
        display: flex;
        gap: 24px;
      }
    }

    .share-hint {
      font-size: 13px;
      color: var(--gray-600);
      margin: 8px 0 0 0;
    }

    .dept-selection {
      margin-top: 12px;
    }
  }
}
</style>
