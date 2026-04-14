<template>
  <div class="model-providers-section">
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">Custom Providers</div>
        <p class="section-description">
          Add custom LLM providers supporting OpenAI-compatible API format.
        </p>
      </div>
      <a-button type="primary" @click="openAddCustomProviderModal" class="add-btn lucide-icon-btn">
        <template #icon>
          <Plus :size="16" />
        </template>
        Add Custom Provider
      </a-button>
    </div>

    <div class="custom-providers-section">
      <!-- Custom provider list -->
      <div
        class="custom-provider-card"
        v-for="(provider, providerId) in customProviders"
        :key="providerId"
      >
        <div class="card-header">
          <div class="provider-info">
            <h4>{{ provider.name }}</h4>
            <span class="provider-id">ID: {{ providerId }}</span>
          </div>
          <div class="provider-actions">
            <a-button
              type="text"
              size="small"
              class="lucide-icon-btn"
              @click="testCustomProvider(providerId, provider.default)"
            >
              <template #icon>
                <PlugZap :size="14" />
              </template>
              Test Connection
            </a-button>
            <a-button
              type="text"
              size="small"
              class="lucide-icon-btn"
              @click="openEditCustomProviderModal(providerId, provider)"
            >
              <template #icon>
                <Pencil :size="14" />
              </template>
              Edit
            </a-button>
            <a-popconfirm
              title="Are you sure you want to delete this custom provider?"
              @confirm="deleteCustomProvider(providerId)"
              ok-text="Confirm"
              cancel-text="Cancel"
            >
              <a-button type="text" size="small" danger class="lucide-icon-btn">
                <template #icon>
                  <Trash2 :size="14" />
                </template>
                Delete
              </a-button>
            </a-popconfirm>
          </div>
        </div>
        <div class="card-content">
          <div class="provider-details">
            <div class="detail-item">
              <span class="label">API URL:</span>
              <span class="value">{{ provider.base_url }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Default Model:</span>
              <span class="value">{{ provider.default }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Available Models:</span>
              <span class="value">{{ provider.models?.join(', ') || 'None' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Empty state when no custom providers -->
      <div v-if="Object.keys(customProviders).length === 0" class="empty-state">
        <a-empty description="No custom providers yet">
          <!-- <a-button type="primary" @click="openAddCustomProviderModal">Add Custom Provider</a-button> -->
        </a-empty>
      </div>
    </div>

    <a-divider />

    <!-- Built-in providers -->
    <div class="builtin-providers-section">
      <div class="section-header">
        <div class="section-subtitle">Built-in Providers</div>
        <div class="providers-stats">
          <span class="stats-item available"> {{ modelKeys.length }} Available </span>
          <span class="stats-item unavailable"> {{ notModelKeys.length }} Unconfigured </span>
        </div>
      </div>
      <p class="section-description">
        Configure the corresponding API key in <code>.env</code> and restart the service
      </p>

      <!-- Configured providers -->
      <div
        class="model-provider-card configured-provider"
        v-for="(item, key) in modelKeys"
        :key="key"
      >
        <div class="card-header" @click="toggleExpand(item)">
          <div :class="{ 'model-icon': true, available: modelStatus[item] }">
            <img :src="modelIcons[item] || modelIcons.default" alt="Model icon" />
          </div>
          <div class="model-title-container">
            <div class="model-name">{{ modelNames[item].name }}</div>
          </div>
          <div class="provider-meta">
            <a-button
              type="text"
              class="expand-button lucide-icon-btn"
              @click.stop="openProviderConfig(item)"
              title="Configure models"
            >
              <Settings :size="14" /> Selected {{ modelNames[item].models?.length || 0 }} models
            </a-button>
          </div>
        </div>
        <div class="card-body-wrapper" :class="{ expanded: expandedModels[item] }">
          <div class="card-body" v-if="modelStatus[item]">
            <div class="card-models" v-for="(model, idx) in modelNames[item].models" :key="idx">
              <div class="model_name">{{ model }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Unconfigured providers -->
      <div
        class="model-provider-card unconfigured-provider"
        v-for="(item, key) in notModelKeys"
        :key="key"
      >
        <div class="card-header">
          <div class="model-icon">
            <img :src="modelIcons[item] || modelIcons.default" alt="Model icon" />
          </div>
          <div class="model-title-container">
            <div class="model-name">{{ modelNames[item].name }}</div>
            <a :href="modelNames[item].url" target="_blank" class="model-url">
              View details <CircleHelp :size="13" />
            </a>
          </div>
          <div class="missing-keys">
            Required<span>{{ modelNames[item].env }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Provider configuration modal -->
    <a-modal
      class="provider-config-modal"
      v-model:open="providerConfig.visible"
      :title="`Configure ${providerConfig.providerName} Models`"
      @ok="saveProviderConfig"
      @cancel="cancelProviderConfig"
      :okText="'Save Config'"
      :cancelText="'Cancel'"
      :ok-type="'primary'"
      :width="800"
    >
      <div v-if="providerConfig.loading" class="modal-loading-container">
        <a-spin :indicator="h(LoaderCircle, { size: 32, color: 'var(--main-color)' })" />
        <div class="loading-text">Fetching model list...</div>
      </div>
      <div v-else class="modal-config-content">
        <div class="modal-config-header">
          <p class="description">
            Select the models you want to enable in the system. The list may include non-chat
            models, so please review carefully.
          </p>
        </div>

        <div class="modal-models-section">
          <!-- Warning: detected unavailable models -->
          <div
            v-if="unsupportedModels.length > 0"
            class="simple-notice warning"
            style="margin-bottom: 20px"
          >
            <p>
              Some configured models are not in the current provider list. These models may be
              unavailable or removed by the provider:
            </p>
            <div class="unsupported-list">
              <a-tag
                closable
                v-for="model in unsupportedModels"
                :key="model"
                color="error"
                @close="removeModel(model)"
                style="margin-bottom: 4px"
              >
                {{ model }}
              </a-tag>
            </div>
            <a-button
              size="small"
              type="primary"
              danger
              ghost
              @click="removeAllUnsupported"
              class="clear-btn"
            >
              Remove All Unavailable Models
            </a-button>
          </div>

          <div class="model-search" v-if="providerConfig.allModels.length > 0">
            <a-input
              v-model:value="providerConfig.searchQuery"
              placeholder="Search models..."
              allow-clear
            >
              <template #prefix>
                <Search :size="14" />
              </template>
            </a-input>
          </div>

          <!-- Selected summary -->
          <div class="selection-summary" v-if="providerConfig.allModels.length > 0">
            <span>Selected {{ providerConfig.selectedModels.length }} models</span>
            <span v-if="providerConfig.searchQuery" class="filter-info">
              (Currently showing {{ filteredModels.length }})
            </span>
          </div>

          <div class="modal-checkbox-list" v-if="providerConfig.allModels.length > 0">
            <div v-for="(model, index) in filteredModels" :key="index" class="modal-checkbox-item">
              <a-checkbox
                :checked="providerConfig.selectedModels.includes(model.id)"
                @change="(e) => handleModelSelect(model.id, e.target.checked)"
              >
                {{ model.id }}
              </a-checkbox>
            </div>
          </div>

          <!-- Manual management mode (when model list cannot be fetched) -->
          <div v-if="providerConfig.allModels.length === 0" class="modal-manual-manage">
            <div
              v-if="!modelStatus[providerConfig.provider]"
              class="simple-notice warning"
              style="margin-bottom: 16px"
            >
              Configure the corresponding API key in .env and restart the service
            </div>

            <div class="manual-manage-container">
              <div class="manual-header">
                <div class="simple-notice info">
                  Unable to fetch the model list. You can manage model configuration manually. This
                  provider may not support automatic model listing yet, or the network request
                  failed. You can add or remove models below.
                </div>
              </div>

              <div class="manual-add-box" style="margin: 16px 0">
                <a-input-search
                  v-model:value="manualModelInput"
                  placeholder="Enter model ID (e.g., gpt-4)"
                  enter-button="Add Model"
                  @search="addManualModel"
                />
              </div>

              <div class="current-models-list">
                <h4 style="margin-bottom: 10px; font-weight: 600">
                  Currently Configured Models ({{ providerConfig.selectedModels.length }})
                </h4>
                <div
                  v-if="providerConfig.selectedModels.length === 0"
                  class="empty-text"
                  style="color: var(--gray-500); padding: 8px 0"
                >
                  No models configured
                </div>
                <div class="tags-container">
                  <a-tag
                    v-for="model in providerConfig.selectedModels"
                    :key="model"
                    closable
                    color="blue"
                    @close="removeModel(model)"
                    style="margin-bottom: 8px; padding: 4px 8px"
                  >
                    {{ model }}
                  </a-tag>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </a-modal>

    <!-- Custom provider configuration modal -->
    <a-modal
      v-model:open="customProviderModal.visible"
      :title="customProviderModal.isEdit ? 'Edit Custom Provider' : 'Add Custom Provider'"
      @ok="saveCustomProvider"
      @cancel="cancelCustomProvider"
      :okText="'Save'"
      :cancelText="'Cancel'"
      :ok-type="'primary'"
      :width="600"
      :confirmLoading="customProviderModal.loading"
    >
      <a-form
        ref="customProviderForm"
        :model="customProviderModal.data"
        :rules="customProviderRules"
        layout="vertical"
      >
        <a-form-item label="Provider ID" name="providerId" v-if="!customProviderModal.isEdit">
          <a-input
            v-model:value="customProviderModal.data.providerId"
            placeholder="Enter a unique provider identifier (e.g., my-provider)"
            :disabled="customProviderModal.isEdit"
          />
        </a-form-item>

        <a-form-item label="Provider Name" name="name">
          <a-input
            v-model:value="customProviderModal.data.name"
            placeholder="Enter provider display name"
          />
        </a-form-item>

        <a-form-item label="API URL" name="base_url">
          <a-input
            v-model:value="customProviderModal.data.base_url"
            placeholder="Enter API base URL (e.g., https://api.example.com/v1)"
          />
        </a-form-item>

        <a-form-item label="Default Model" name="default">
          <a-input
            v-model:value="customProviderModal.data.default"
            placeholder="Enter default model name"
          />
        </a-form-item>

        <a-form-item label="API Key" name="env">
          <a-input
            v-model:value="customProviderModal.data.env"
            placeholder="Enter API key or environment variable name (e.g., MY_API_KEY)"
          />
          <div class="form-help-text">
            You can enter an API key directly or use an environment variable name (e.g.,
            MY_API_KEY). If no key is needed, enter "none".
          </div>
        </a-form-item>

        <a-form-item label="Supported Models" name="models">
          <a-textarea
            v-model:value="customProviderModal.data.modelsText"
            placeholder="Enter supported models, one model per line"
            :rows="4"
          />
          <div class="form-help-text">Enter one model name per line, e.g., gpt-5</div>
        </a-form-item>

        <a-form-item label="Documentation URL" name="url">
          <a-input
            v-model:value="customProviderModal.data.url"
            placeholder="Enter provider documentation URL (optional)"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, reactive, watch, h, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  CircleHelp,
  Settings,
  LoaderCircle,
  Search,
  Plus,
  Pencil,
  Trash2,
  PlugZap
} from 'lucide-vue-next'
import { useConfigStore } from '@/stores/config'
import { modelIcons } from '@/utils/modelIcon'
import { agentApi } from '@/apis/agent_api'
import { customProviderApi } from '@/apis/system_api'

const configStore = useConfigStore()

// Computed properties
const modelNames = computed(() => configStore.config?.model_names)
const modelStatus = computed(() => configStore.config?.model_provider_status)

// Computed custom providers
const customProviders = computed(() => {
  const providers = configStore.config?.model_names || {}
  return Object.fromEntries(Object.entries(providers).filter(([, value]) => value.custom === true))
})

// Provider configuration state
const providerConfig = reactive({
  visible: false,
  provider: '',
  providerName: '',
  models: [],
  allModels: [], // all available models
  selectedModels: [], // user-selected models
  loading: false,
  searchQuery: ''
})

// Filter keys where modelStatus is true
const modelKeys = computed(() => {
  return Object.keys(modelStatus.value || {}).filter(
    (key) => modelStatus.value[key] && !customProviders.value[key]
  )
})

// Filter keys where modelStatus is false
const notModelKeys = computed(() => {
  return Object.keys(modelStatus.value || {}).filter((key) => !modelStatus.value[key])
})

// Model expansion state
const expandedModels = reactive({})

// Watch modelKeys and default-expand newly added models
watch(
  modelKeys,
  (newKeys) => {
    newKeys.forEach((key) => {
      if (expandedModels[key] === undefined) {
        expandedModels[key] = true
      }
    })
  },
  { immediate: true }
)

// Toggle expand state
const toggleExpand = (item) => {
  expandedModels[item] = !expandedModels[item]
}

// Handle model selection
const handleModelSelect = (modelId, checked) => {
  const selectedModels = providerConfig.selectedModels
  const index = selectedModels.indexOf(modelId)

  if (checked && index === -1) {
    selectedModels.push(modelId)
  } else if (!checked && index > -1) {
    selectedModels.splice(index, 1)
  }
}

// Open provider configuration
const openProviderConfig = (provider) => {
  providerConfig.provider = provider
  providerConfig.providerName = modelNames.value[provider].name
  providerConfig.allModels = []
  providerConfig.visible = true
  providerConfig.loading = true
  providerConfig.searchQuery = '' // reset search query

  // Use currently selected models as initial values
  const currentModels = modelNames.value[provider]?.models || []
  providerConfig.selectedModels = [...currentModels]

  // Fetch all available models
  fetchProviderModels(provider)
}

// Fetch model list for a provider
const fetchProviderModels = (provider) => {
  providerConfig.loading = true
  agentApi
    .getProviderModels(provider)
    .then((data) => {
      console.log(`${provider} model list:`, data)

      // Handle possible API response formats
      let modelsList = []

      // Case 1: { data: [...] }
      if (data.data && Array.isArray(data.data)) {
        modelsList = data.data
      }
      // Case 2: { models: [...] } (string array)
      else if (data.models && Array.isArray(data.models)) {
        modelsList = data.models.map((model) => (typeof model === 'string' ? { id: model } : model))
      }
      // Case 3: { models: { data: [...] } }
      else if (data.models && data.models.data && Array.isArray(data.models.data)) {
        modelsList = data.models.data
      }

      console.log('Processed model list:', modelsList)
      providerConfig.allModels = modelsList
      providerConfig.loading = false
    })
    .catch((error) => {
      console.error(`Failed to fetch model list for ${provider}:`, error)
      message.error({
        content: `Failed to fetch model list for ${modelNames.value[provider].name}`,
        duration: 2
      })
      providerConfig.loading = false
    })
}

// Save provider configuration
const saveProviderConfig = async () => {
  if (!modelStatus.value[providerConfig.provider]) {
    message.error('Configure the corresponding API key in .env and restart the service')
    return
  }

  message.loading({ content: 'Saving configuration...', key: 'save-config', duration: 0 })

  try {
    // Send selected models to backend
    const data = await agentApi.updateProviderModels(
      providerConfig.provider,
      providerConfig.selectedModels
    )
    console.log('Updated model list:', data.models)

    message.success({ content: 'Model configuration saved!', key: 'save-config', duration: 2 })

    // Close modal
    providerConfig.visible = false

    // Refresh config
    configStore.refreshConfig()
  } catch (error) {
    console.error('Failed to save configuration:', error)
    message.error({
      content: 'Failed to save configuration: ' + error.message,
      key: 'save-config',
      duration: 2
    })
  }
}

// Cancel provider configuration
const cancelProviderConfig = () => {
  providerConfig.visible = false
}

// Computed filtered model list
const filteredModels = computed(() => {
  const allModels = providerConfig.allModels || []
  const searchQuery = providerConfig.searchQuery.toLowerCase()
  return allModels.filter((model) => model.id.toLowerCase().includes(searchQuery))
})

// Computed unsupported or unavailable models
const unsupportedModels = computed(() => {
  if (providerConfig.allModels.length === 0) return []
  const availableIds = new Set(providerConfig.allModels.map((m) => m.id))
  return providerConfig.selectedModels.filter((id) => !availableIds.has(id))
})

// Manual management state
const manualModelInput = ref('')

// Add a manually entered model
const addManualModel = () => {
  const val = manualModelInput.value.trim()
  if (!val) return

  if (providerConfig.selectedModels.includes(val)) {
    message.warning('Model already exists')
    return
  }

  providerConfig.selectedModels.push(val)
  manualModelInput.value = ''
  message.success('Added successfully')
}

// Remove model
const removeModel = (modelId) => {
  const idx = providerConfig.selectedModels.indexOf(modelId)
  if (idx > -1) {
    providerConfig.selectedModels.splice(idx, 1)
  }
}

// Remove all unsupported models
const removeAllUnsupported = () => {
  const toRemove = unsupportedModels.value
  providerConfig.selectedModels = providerConfig.selectedModels.filter(
    (id) => !toRemove.includes(id)
  )
  message.success(`Removed ${toRemove.length} unavailable models`)
}

// Custom provider management
const customProviderForm = ref()
const customProviderModal = reactive({
  visible: false,
  isEdit: false,
  loading: false,
  data: {
    providerId: '',
    name: '',
    base_url: '',
    default: '',
    env: '',
    modelsText: '',
    models: [],
    url: ''
  }
})

// Validation rules for custom provider form
const customProviderRules = {
  providerId: [
    { required: true, message: 'Please enter provider ID', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9_-]+$/,
      message: 'Provider ID can only contain letters, numbers, underscores, and hyphens',
      trigger: 'blur'
    },
    {
      validator: (rule, value) => {
        if (!value) return Promise.resolve()
        // Check for duplicate provider ID
        if (modelNames.value && modelNames.value[value]) {
          return Promise.reject('Provider ID already exists, please use another one')
        }
        return Promise.resolve()
      },
      trigger: 'blur'
    }
  ],
  name: [{ required: true, message: 'Please enter provider name', trigger: 'blur' }],
  base_url: [
    { required: true, message: 'Please enter API URL', trigger: 'blur' },
    { type: 'url', message: 'Please enter a valid URL', trigger: 'blur' }
  ],
  default: [{ required: true, message: 'Please enter default model', trigger: 'blur' }],
  env: [
    { required: true, message: 'Please enter API key or environment variable', trigger: 'blur' }
  ]
}

// Open add custom provider modal
const openAddCustomProviderModal = () => {
  customProviderModal.visible = true
  customProviderModal.isEdit = false
  resetCustomProviderForm()
}

// Open edit custom provider modal
const openEditCustomProviderModal = (providerId, provider) => {
  customProviderModal.visible = true
  customProviderModal.isEdit = true

  // Fill form data
  customProviderModal.data.providerId = providerId
  customProviderModal.data.name = provider.name
  customProviderModal.data.base_url = provider.base_url
  customProviderModal.data.default = provider.default
  customProviderModal.data.env = provider.env
  customProviderModal.data.models = provider.models || []
  customProviderModal.data.modelsText = (provider.models || []).join('\n')
  customProviderModal.data.url = provider.url || ''
}

// Reset custom provider form
const resetCustomProviderForm = () => {
  customProviderModal.data = {
    providerId: '',
    name: '',
    base_url: '',
    default: '',
    env: '',
    modelsText: '',
    models: [],
    url: ''
  }
  customProviderForm.value?.resetFields()
}

// Save custom provider
const saveCustomProvider = async () => {
  try {
    await customProviderForm.value.validate()
    customProviderModal.loading = true

    // Process model list
    const models = customProviderModal.data.modelsText
      .split('\n')
      .map((model) => model.trim())
      .filter((model) => model.length > 0)

    // Validate that the default model exists in supported models
    if (models.length > 0 && !models.includes(customProviderModal.data.default)) {
      message.error(
        `Default model "${customProviderModal.data.default}" is not in supported models`
      )
      customProviderModal.loading = false
      return
    }

    const providerData = {
      name: customProviderModal.data.name,
      base_url: customProviderModal.data.base_url,
      default: customProviderModal.data.default,
      env: customProviderModal.data.env,
      models: models,
      url: customProviderModal.data.url,
      custom: true
    }

    if (customProviderModal.isEdit) {
      await customProviderApi.updateCustomProvider(
        customProviderModal.data.providerId,
        providerData
      )
      message.success('Custom provider updated successfully')
    } else {
      await customProviderApi.addCustomProvider(customProviderModal.data.providerId, providerData)
      message.success(`Custom provider ${customProviderModal.data.providerId} added successfully`)
    }

    // Close modal and refresh config
    customProviderModal.visible = false
    await configStore.refreshConfig()
  } catch (error) {
    if (error.errorFields) {
      // Form validation error
      return
    }

    // Handle API error response
    let errorMessage = 'Unknown error'
    if (error.response?.data?.detail) {
      errorMessage = error.response.data.detail
    } else if (error.message) {
      errorMessage = error.message
    } else if (typeof error === 'string') {
      errorMessage = error
    }

    message.error(`Operation failed: ${errorMessage}`)
  } finally {
    customProviderModal.loading = false
  }
}

// Cancel custom provider operation
const cancelCustomProvider = () => {
  customProviderModal.visible = false
  resetCustomProviderForm()
}

// Delete custom provider
const deleteCustomProvider = async (providerId) => {
  try {
    await customProviderApi.deleteCustomProvider(providerId)
    message.success('Custom provider deleted successfully')
    await configStore.refreshConfig()
  } catch (error) {
    message.error(
      `Deletion failed: ${error.message || error.response?.data?.detail || 'Unknown error'}`
    )
  }
}

// Test custom provider connection
const testCustomProvider = async (providerId, modelName) => {
  try {
    message.loading({ content: 'Testing connection...', key: 'test-connection', duration: 0 })

    const result = await customProviderApi.testCustomProvider(providerId, modelName)

    if (result.status?.status === 'available') {
      message.success({
        content: 'Connection test successful',
        key: 'test-connection',
        duration: 2
      })
    } else {
      message.error({
        content: `Connection test failed: ${result.status?.message || 'Unknown error'}`,
        key: 'test-connection',
        duration: 3
      })
    }
  } catch (error) {
    message.error({
      content: `Test failed: ${error.message || error.response?.data?.detail || 'Unknown error'}`,
      key: 'test-connection',
      duration: 3
    })
  }
}
</script>

<style lang="less" scoped>
.custom-providers-section {
  margin-bottom: 24px;
  .custom-provider-card {
    border: 1px solid var(--gray-200);
    background: var(--gray-0);
    border-radius: 8px;
    margin-bottom: 12px;
    overflow: hidden;
    box-shadow: 0 1px 3px var(--shadow-1);

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      background: var(--gray-25);
      border-bottom: 1px solid var(--gray-200);

      .provider-info {
        display: flex;
        align-items: center;
        gap: 12px;

        h4 {
          margin: 0;
          font-weight: 500;
          color: var(--gray-900);
        }

        .provider-id {
          color: var(--gray-600);
          padding: 2px 8px;
          font-size: 12px;
          font-weight: 500;
        }
      }

      .provider-actions {
        display: flex;
        gap: 0px;
      }
    }

    .card-content {
      padding: 8px 12px;

      .provider-details {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 12px 8px;

        .detail-item {
          display: flex;
          flex-direction: column;

          .label {
            font-size: 12px;
            color: var(--gray-600);
            font-weight: 500;
          }

          .value {
            font-size: 14px;
            color: var(--gray-900);
            word-break: break-all;
          }
        }
      }
    }
  }

  .empty-state {
    text-align: center;
    padding: 10px 20px;
    background: var(--gray-25);
    border-radius: 8px;
    border: 1px dashed var(--gray-300);
  }
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;

  .section-subtitle {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: var(--gray-900);
  }
}

.builtin-providers-section {
  .section-header {
    .providers-stats {
      display: flex;
      gap: 12px;
      font-size: 13px;

      .stats-item {
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 12px;

        &.available {
          background: var(--color-success-50);
          color: var(--color-success-700);
        }

        &.unavailable {
          background: var(--color-warning-50);
          color: var(--color-warning-700);
        }
      }
    }
  }
}

// Form help text style
.form-help-text {
  font-size: 12px;
  color: var(--gray-600);
  margin-top: 4px;
  line-height: 1.4;
}

.model-provider-card {
  border: 1px solid var(--gray-150);
  background-color: var(--gray-0);
  border-radius: 8px;
  margin: 16px 0;
  padding: 0;
  overflow: hidden;

  // Styles for configured providers
  &.configured-provider {
    .model-icon {
      filter: grayscale(0%);
    }
  }

  // Styles for unconfigured providers
  &.unconfigured-provider {
    .card-header {
      background: var(--gray-25);

      .model-name {
        color: var(--gray-700);
        font-weight: 500;
      }

      .model-icon {
        filter: grayscale(100%);
      }
    }
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
    padding: 6px 10px;
    background: var(--gray-0);

    .model-title-container {
      display: flex;
      flex-direction: column;
      flex: 1;

      .model-name {
        margin: 0;
        font-size: 14px;
        font-weight: 600;
        color: var(--gray-900);
      }
    }

    .model-url {
      font-size: 12px;
      width: fit-content;
      color: var(--gray-500);
      transition: color 0.2s ease;

      &:hover {
        color: var(--main-color);
      }
    }

    .model-icon {
      width: 32px;
      height: 32px;
      border-radius: 6px;
      overflow: hidden;
      filter: grayscale(100%);
      flex-shrink: 0;
      background-color: white;
      // border: 1px solid var(--gray-200);

      img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        padding: 4px;
        border-radius: 8px;
      }

      &.available {
        filter: grayscale(0%);
      }
    }

    .expand-button,
    .config-button {
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 4px 6px;
      cursor: pointer;
      color: var(--gray-800);
      border-radius: 6px;
      transition: all 0.2s ease;
      font-size: 12px;

      &:hover {
        background-color: var(--gray-50);
        color: var(--gray-700);
      }
    }

    a {
      text-decoration: none;
      color: var(--gray-500);
      font-size: 12px;
      transition: all 0.2s ease;

      &:hover {
        color: var(--main-color);
      }
    }

    .missing-keys {
      margin-left: auto;
      color: var(--gray-700);
      font-size: 12px;
      font-weight: 500;

      & > span {
        margin-left: 6px;
        user-select: all;
        background-color: var(--color-warning-50);
        color: var(--color-warning-700);
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 11px;
        border: 1px solid var(--color-warning-100);
      }
    }
  }

  .card-body-wrapper {
    max-height: 0;
    overflow: hidden;
    background: var(--gray-0);

    &.expanded {
      max-height: 800px;
    }
  }

  .card-body {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 8px;
    padding: 10px;
    padding-top: 4px;

    // Standard model card style
    .card-models {
      width: 100%;
      border-radius: 6px;
      border: 1px solid var(--gray-150);
      padding: 8px 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-sizing: border-box;
      background: var(--gray-0);
      // min-height: 48px;

      .model_name {
        font-size: 14px;
        font-weight: 500;
        color: var(--gray-900);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        line-height: 1.4;
      }
    }
  }
}

.provider-config-modal {
  .ant-modal-body {
    padding: 16px 0 !important;
    .modal-loading-container {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      height: 200px;

      .loading-text {
        margin-top: 20px;
        color: var(--gray-700);
        font-size: 14px;
      }
    }

    .modal-config-content {
      max-height: 70vh;
      overflow-y: auto;

      .modal-config-header {
        margin-bottom: 20px;

        .description {
          font-size: 14px;
          color: var(--gray-600);
          margin: 0;
        }
      }

      .modal-models-section {
        .model-search {
          margin-bottom: 10px;
          padding: 0;

          .ant-input-affix-wrapper {
            border-radius: 6px;
          }
        }
        .selection-summary {
          margin: 0 6px 10px;
          font-size: 14px;
          color: var(--gray-600);

          .filter-info {
            color: var(--gray-500);
          }
        }
        .modal-checkbox-list {
          max-height: 50vh;
          overflow-y: auto;
          .modal-checkbox-item {
            display: inline-block;
            margin-bottom: 4px;
            margin-right: 4px;
            padding: 4px 6px;
            border-radius: 6px;
            background-color: var(--gray-0);
            border: 1px solid var(--gray-150);
          }
        }
      }
    }
  }
}

// Additional style adjustments for different states
.unconfigured-provider {
  .card-body {
    .card-models {
      opacity: 0.6;
      pointer-events: none;

      .model_name {
        color: var(--gray-500);
      }
    }
  }
}

// Simple Notice Styles
.simple-notice {
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  margin-bottom: 12px;
  border: 1px solid transparent; // Keep a subtle border

  &.warning {
    background-color: var(--color-warning-50);
    color: var(--color-warning-700);
    border-color: var(--color-warning-100);
  }

  &.info {
    background-color: var(--color-info-50);
    color: var(--color-info-700);
    border-color: var(--color-info-100);
  }

  p {
    // For warning message, if it's multiline
    margin: 0;
  }

  .unsupported-list {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .clear-btn {
    margin-top: 8px;
    font-size: 12px;
    height: 24px;
    padding: 0 8px;
  }
}
</style>
