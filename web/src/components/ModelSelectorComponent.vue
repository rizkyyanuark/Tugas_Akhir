<template>
  <a-dropdown trigger="click">
    <div class="model-select" :class="modelSelectClasses" @click.prevent>
      <div class="model-select-content">
        <div class="model-info">
          <a-tooltip :title="displayModelText" placement="right">
            <span class="model-text text"> {{ displayModelText }} </span>
          </a-tooltip>
          <span class="model-provider">{{ displayModelProvider }}</span>
        </div>
        <div class="model-status-controls">
          <span
            v-if="currentModelStatus"
            class="model-status-indicator"
            :class="currentModelStatus.status"
            :title="getCurrentModelStatusTooltip()"
          >
            {{ modelStatusIcon }}
          </span>
          <a-button
            :size="buttonSize"
            type="text"
            :loading="state.checkingStatus"
            @click.stop="checkCurrentModelStatus"
            :disabled="state.checkingStatus"
            class="status-check-button"
          >
            {{ state.checkingStatus ? 'Checking...' : 'Check' }}
          </a-button>
        </div>
      </div>
    </div>
    <template #overlay>
      <a-menu class="scrollable-menu">
        <a-menu-item-group
          v-for="(item, key) in modelKeys"
          :key="key"
          :title="modelNames[item]?.name"
        >
          <a-menu-item
            v-for="(model, idx) in modelNames[item]?.models"
            :key="`${item}-${idx}`"
            @click="handleSelectModel(item, model)"
          >
            {{ model }}
          </a-menu-item>
        </a-menu-item-group>
      </a-menu>
    </template>
  </a-dropdown>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { useConfigStore } from '@/stores/config'
import { chatModelApi } from '@/apis/system_api'

const props = defineProps({
  model_spec: {
    type: String,
    default: ''
  },
  sep: {
    type: String,
    default: '/'
  },
  placeholder: {
    type: String,
    default: 'Please select a model'
  },
  size: {
    type: String,
    default: 'small',
    validator: (value) => ['small', 'middle', 'large'].includes(value)
  }
})

const configStore = useConfigStore()
const emit = defineEmits(['select-model'])

// State management
const state = reactive({
  currentModelStatus: null, // Current model status
  checkingStatus: false // Whether status check is running
})

// Get required data from configStore
const modelNames = computed(() => configStore.config?.model_names)
const modelStatus = computed(() => configStore.config?.model_provider_status)

// Filter keys where modelStatus is true
const modelKeys = computed(() => {
  return Object.keys(modelStatus.value || {}).filter((key) => modelStatus.value?.[key])
})

const resolvedSep = computed(() => props.sep || '/')
const resolvedSize = computed(() => props.size || 'small')
const modelSelectClasses = computed(() => ({
  'model-select--middle': resolvedSize.value === 'middle',
  'model-select--large': resolvedSize.value === 'large'
}))
const buttonSize = computed(() => {
  if (resolvedSize.value === 'large') return 'large'
  if (resolvedSize.value === 'middle') return 'middle'
  return 'small'
})

const resolvedModel = computed(() => {
  const spec = props.model_spec || ''
  const sep = resolvedSep.value
  if (spec && sep) {
    const index = spec.indexOf(sep)
    if (index !== -1) {
      const provider = spec.slice(0, index)
      const name = spec.slice(index + sep.length)
      if (provider && name) {
        return { provider, name }
      }
    }
  }
  return { provider: '', name: '' }
})

const displayModelProvider = computed(() => resolvedModel.value.provider || '')
const displayModelName = computed(() => resolvedModel.value.name || '')
const displayModelText = computed(() => displayModelName.value || props.placeholder)

// Current model status
const currentModelStatus = computed(() => {
  return state.currentModelStatus
})

// Check current model status
const checkCurrentModelStatus = async () => {
  const { provider, name } = resolvedModel.value
  if (!provider || !name) return

  try {
    state.checkingStatus = true
    const response = await chatModelApi.getModelStatus(provider, name)
    if (response.status) {
      state.currentModelStatus = response.status
    } else {
      state.currentModelStatus = null
    }
  } catch (error) {
    console.error(`Failed to check status of current model ${provider}/${name}:`, error)
    state.currentModelStatus = { status: 'error', message: error.message }
  } finally {
    state.checkingStatus = false
  }
}

const modelStatusIcon = computed(() => {
  const status = currentModelStatus.value
  if (!status) return '○'
  if (status.status === 'available') return '✓'
  if (status.status === 'unavailable') return '✗'
  if (status.status === 'error') return '⚠'
  return '○'
})

// Get tooltip text for current model status
const getCurrentModelStatusTooltip = () => {
  const status = currentModelStatus.value
  if (!status) return 'Unknown status'

  let statusText = ''
  if (status.status === 'available') statusText = 'Available'
  else if (status.status === 'unavailable') statusText = 'Unavailable'
  else if (status.status === 'error') statusText = 'Error'

  const message = status.message || 'No details'
  return `${statusText}: ${message}`
}

// Model selection handler
const handleSelectModel = async (provider, name) => {
  const sep = resolvedSep.value || '/'
  const separator = sep || '/'
  const spec = `${provider}${separator}${name}`
  emit('select-model', spec)
}
</script>

<style lang="less" scoped>
// Variable definitions
@status-success: var(--color-success-500);
@status-error: var(--color-error-500);
@status-warning: var(--color-warning-500);
@status-default: var(--gray-500);
@border-radius: 8px;
@scrollbar-width: 6px;
@status-indicator-padding: 2px 4px;
@status-check-button-padding: 0 4px;
@status-check-button-font-size: 12px;
@status-indicator-font-size: 11px;
@model-provider-color: var(--gray-500);

// Main selector styles
.model-select {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 4px 8px;
  cursor: pointer;
  border: 1px solid var(--gray-200);
  border-radius: @border-radius;
  background-color: var(--gray-0);
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;

  // Modifier classes
  &.borderless {
    border: none;
  }

  &.max-width {
    max-width: 380px;
  }

  &.model-select--middle {
    font-size: 15px;
  }

  &.model-select--large {
    font-size: 16px;
  }

  // Content area
  .model-select-content {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    width: 100%;

    // Model info area
    .model-info {
      flex: 1;
      min-width: 0;
      overflow: hidden;

      .model-text {
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--gray-1000);
        white-space: nowrap;
      }

      .model-provider {
        color: @model-provider-color;
        margin-left: 4px;
      }
    }

    // Status controls area
    .model-status-controls {
      display: flex;
      align-items: center;
      gap: 4px;
      flex: 0;
      margin-left: auto;

      // Status indicator
      .model-status-indicator {
        font-size: @status-indicator-font-size;
        font-weight: bold;
        padding: @status-indicator-padding;
        border-radius: 3px;

        // Status style modifiers
        &.available {
          color: @status-success;
        }

        &.unavailable {
          color: @status-error;
        }

        &.error {
          color: @status-warning;
        }
      }

      // Check button
      .status-check-button {
        font-size: @status-check-button-font-size;
        padding: @status-check-button-padding;
      }
    }
  }
}

// Scrollable menu styles
.scrollable-menu {
  max-height: 300px;
  overflow-y: auto;

  // Custom scrollbar styles
  &::-webkit-scrollbar {
    width: @scrollbar-width;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
    border-radius: 3px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--gray-400);
    border-radius: 3px;

    &:hover {
      background: var(--gray-500);
    }
  }
}
</style>

<style lang="less" scoped>
// Move global styles into scoped to avoid style pollution
:deep(.ant-dropdown-menu) {
  &.scrollable-menu {
    max-height: 300px;
    overflow-y: auto;
  }
}
</style>
