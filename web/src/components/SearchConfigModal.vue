<template>
  <a-modal
    :open="props.modelValue"
    title="Retrieval Settings"
    width="800px"
    :confirm-loading="loading"
    @ok="handleSave"
    @cancel="handleCancel"
    ok-text="Save"
    cancel-text="Cancel"
  >
    <div class="search-config-modal">
      <div v-if="loading" class="config-loading">
        <a-spin size="large" />
        <p>Loading configuration parameters...</p>
      </div>

      <div v-else-if="error" class="config-error">
        <a-result status="error" title="Failed to Load Configuration" :sub-title="error">
          <template #extra>
            <a-button type="primary" @click="loadQueryParams">Reload</a-button>
          </template>
        </a-result>
      </div>

      <div v-else class="config-forms">
        <a-form layout="vertical">
          <a-row :gutter="16">
            <a-col :span="12" v-for="param in queryParams" :key="param.key">
              <a-form-item :label="param.label">
                <template #extra v-if="param.description">
                  <div class="param-description">{{ param.description }}</div>
                </template>
                <a-select
                  v-if="param.type === 'select'"
                  v-model:value="meta[param.key]"
                  style="width: 100%"
                >
                  <a-select-option
                    v-for="option in param.options"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </a-select-option>
                </a-select>
                <a-select
                  v-else-if="param.type === 'boolean'"
                  :value="computedMeta[param.key]"
                  @update:value="(value) => updateMeta(param.key, value)"
                  style="width: 100%"
                >
                  <a-select-option value="true">Enabled</a-select-option>
                  <a-select-option value="false">Disabled</a-select-option>
                </a-select>
                <a-input-number
                  v-else-if="param.type === 'number'"
                  v-model:value="meta[param.key]"
                  style="width: 100%"
                  :min="param.min || 0"
                  :max="param.max || 100"
                />
              </a-form-item>
            </a-col>
          </a-row>
        </a-form>
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useDatabaseStore } from '@/stores/database'
import { message } from 'ant-design-vue'
import { queryApi } from '@/apis/knowledge_api'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  databaseId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'save'])

const store = useDatabaseStore()

// Reactive state
const loading = ref(false)
const error = ref('')
const queryParams = ref([])
const meta = reactive({})

// Computed: handle two-way binding for boolean fields
const computedMeta = computed(() => {
  const result = {}
  for (const key in meta) {
    const param = queryParams.value.find((p) => p.key === key)
    if (param?.type === 'boolean') {
      // For booleans, return string values for select while keeping internal value boolean
      result[key] = meta[key].toString()
    } else {
      result[key] = meta[key]
    }
  }
  return result
})

// Handle value updates
const updateMeta = (key, value) => {
  const param = queryParams.value.find((p) => p.key === key)
  if (param?.type === 'boolean') {
    // Convert string back to boolean
    meta[key] = value === 'true'
  } else {
    meta[key] = value
  }
}

// Load query parameters
const loadQueryParams = async () => {
  try {
    loading.value = true
    error.value = ''

    // Skip request if databaseId is missing
    if (!props.databaseId) {
      queryParams.value = []
      loading.value = false
      return
    }

    const response = await queryApi.getKnowledgeBaseQueryParams(props.databaseId)
    queryParams.value = response.params?.options || []

    // Remove include_distances from UI; it defaults to true and is not editable
    queryParams.value = queryParams.value.filter((param) => param.key !== 'include_distances')

    // Initialize meta object
    queryParams.value.forEach((param) => {
      if (param.default !== undefined) {
        // Ensure boolean defaults are stored as booleans
        if (param.type === 'boolean') {
          meta[param.key] = Boolean(param.default)
        } else {
          meta[param.key] = param.default
        }
      }
    })

    // Ensure include_distances is always true even if not shown
    meta['include_distances'] = true

    // Load persisted configuration
    loadSavedConfig()
  } catch (err) {
    console.error('Failed to load query params:', err)
    error.value = err.message || 'Failed to load query parameters'
  } finally {
    loading.value = false
  }
}

// Load saved configuration
const loadSavedConfig = () => {
  if (!props.databaseId) return

  const saved = localStorage.getItem(`search-config-${props.databaseId}`)
  if (saved) {
    try {
      const savedConfig = JSON.parse(saved)

      // Convert persisted boolean string values back to booleans
      queryParams.value.forEach((param) => {
        if (param.type === 'boolean' && savedConfig[param.key] !== undefined) {
          // Convert string value to boolean
          if (typeof savedConfig[param.key] === 'string') {
            savedConfig[param.key] = savedConfig[param.key] === 'true'
          }
        }
      })

      Object.assign(meta, savedConfig)
    } catch (e) {
      console.warn('Failed to parse saved config:', e)
    }
  }
  // Ensure include_distances stays true and overrides saved values
  meta['include_distances'] = true
}

// Reset to defaults
const resetToDefaults = () => {
  queryParams.value.forEach((param) => {
    if (param.default !== undefined) {
      meta[param.key] = param.default
    }
  })
  // Ensure include_distances always remains true
  meta['include_distances'] = true
  message.success('Reset to default configuration')
}

defineExpose({ resetToDefaults })

// Save configuration
const handleSave = async () => {
  // Skip save if databaseId is missing
  if (!props.databaseId) {
    message.error('Cannot save configuration: missing knowledge base ID')
    return
  }

  // Ensure include_distances always remains true
  meta['include_distances'] = true

  // Persist to knowledge base metadata first
  try {
    const response = await queryApi.updateKnowledgeBaseQueryParams(props.databaseId, meta)
    if (response.message === 'success') {
      // Save to localStorage after server success for compatibility
      localStorage.setItem(`search-config-${props.databaseId}`, JSON.stringify(meta))
      message.success('Configuration saved')

      // Update config in store
      Object.assign(store.meta, meta)

      // Emit save event
      emit('save', { ...meta })
      emit('update:modelValue', false)
    } else {
      throw new Error(response.message || 'Save failed')
    }
  } catch (error) {
    console.error('Failed to save configuration to knowledge base:', error)
    message.error('Failed to save configuration: ' + error.message)
  }
}

// Handle cancel
const handleCancel = () => {
  emit('update:modelValue', false)
}

// Load data when modal opens
watch(
  () => props.modelValue,
  (newVal) => {
    if (newVal && props.databaseId) {
      loadQueryParams()
    }
  }
)
</script>

<style lang="less" scoped>
.config-loading,
.config-error {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  height: 300px;
  color: var(--gray-500);

  p {
    margin-top: 16px;
    font-size: 14px;
  }
}

.config-forms {
  max-width: 100%;
}

.param-description {
  font-size: 12px;
  color: var(--gray-500);
  line-height: 1.5;
  margin-top: 4px;
}

// Form style adjustments
:deep(.ant-form-item) {
  margin-bottom: 16px;
}

:deep(.ant-form-item-label > label) {
  font-weight: 500;
  color: var(--gray-700);
}

:deep(.ant-input),
:deep(.ant-select-selector) {
  border-radius: 6px;
}

:deep(.ant-switch) {
  background-color: var(--gray-300);

  &.ant-switch-checked {
    background-color: var(--main-color);
  }
}
</style>
