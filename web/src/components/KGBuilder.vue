<template>
  <div class="kg-builder">
    <!-- Active Build Card -->
    <a-card
      v-if="state.currentBuild"
      class="active-build-card"
      :title="'Build Status: ' + statusLabel"
      :bordered="false"
    >
      <template #extra>
        <a-tag :color="statusColor">{{ state.currentBuild.status.toUpperCase() }}</a-tag>
      </template>

      <div class="build-progress">
        <a-progress
          :percent="state.currentBuild.progress"
          :status="progressStatus"
          :stroke-width="12"
          stroke-linecap="round"
        />
        <div class="progress-message">
          <LoadingOutlined v-if="isRunning" style="margin-right: 8px" />
          {{ state.currentBuild.message || 'Waiting...' }}
        </div>
      </div>

      <div class="build-metrics" v-if="state.currentBuild.start_time">
        <div class="metric-item">
          <span class="label">Started:</span>
          <span class="value">{{ formatTime(state.currentBuild.start_time) }}</span>
        </div>
        <div class="metric-item">
          <span class="label">Duration:</span>
          <span class="value">{{ formatDuration(state.currentBuild.duration) }}</span>
        </div>
      </div>

      <div class="build-actions">
        <a-button
          v-if="isRunning"
          type="primary"
          danger
          @click="stopBuild"
          :loading="state.stopping"
        >
          <StopOutlined /> Stop Build
        </a-button>
        <a-button v-else type="primary" @click="openStartModal">
          <PlayCircleOutlined /> Start New Build
        </a-button>
      </div>

      <a-alert
        v-if="state.currentBuild.error"
        :message="'Error: ' + state.currentBuild.error"
        type="error"
        show-icon
        class="build-error-alert"
      />
    </a-card>

    <!-- History List -->
    <div class="build-history" v-if="state.history && state.history.length > 0">
      <div class="section-title">Build History</div>
      <a-list :data-source="state.history" size="small">
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="formatTime(item.created_at)"
              :description="
                item.message || (item.status === 'completed' ? 'Successfully built' : 'Failed')
              "
            >
              <template #avatar>
                <div class="history-bullet" :class="item.status"></div>
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
    </div>

    <!-- Start Build Modal -->
    <a-modal
      v-model:open="state.showStartModal"
      title="Start Knowledge Graph Construction"
      @ok="startBuild"
      :confirm-loading="state.starting"
      ok-text="Launch Build"
      cancel-text="Cancel"
    >
      <a-form layout="vertical">
        <a-form-item
          label="LLM Configuration"
          help="Configure which provider/model KG Builder should use for entity resolution and curation."
        >
          <a-radio-group v-model:value="state.options.use_system_llm" button-style="solid">
            <a-radio-button :value="true">Use System Default</a-radio-button>
            <a-radio-button :value="false">Custom For This Run</a-radio-button>
          </a-radio-group>
        </a-form-item>

        <a-form-item v-if="state.options.use_system_llm" label="System Default LLM">
          <a-alert
            :message="systemDefaultModel || 'No default model found in System Settings'"
            :type="systemDefaultModel ? 'info' : 'warning'"
            show-icon
          />
        </a-form-item>

        <a-form-item
          v-else
          label="Custom LLM Model"
          help="You can use the Check button to verify provider/model availability before launching."
        >
          <ModelSelectorComponent
            :model_spec="state.options.llm_model_spec"
            placeholder="Select provider/model for this KG run"
            size="middle"
            @select-model="handleLlmSelect"
          />
        </a-form-item>

        <a-form-item label="Test Mode" help="Run on a small subset of papers for verification.">
          <a-switch v-model:checked="state.options.test_mode" />
        </a-form-item>

        <a-form-item label="Max Papers" v-if="!state.options.test_mode">
          <a-input-number
            v-model:value="state.options.max_papers"
            :min="1"
            :max="10000"
            style="width: 100%"
          />
        </a-form-item>

        <a-form-item label="Clear Database" help="Wipe existing graph data before starting.">
          <a-checkbox v-model:checked="state.options.clear_db"
            >Confirm clear existing data</a-checkbox
          >
        </a-form-item>

        <a-alert
          message="Resource Intensive"
          description="KG construction involves heavy LLM processing and high memory usage. Ensure the server has sufficient resources."
          type="warning"
          show-icon
        />
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { reactive, onMounted, onUnmounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import { LoadingOutlined, StopOutlined, PlayCircleOutlined } from '@ant-design/icons-vue'
import { unifiedApi } from '@/apis/graph_api'
import { useConfigStore } from '@/stores/config'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import dayjs from 'dayjs'

const configStore = useConfigStore()

const state = reactive({
  currentBuild: null,
  history: [],
  pollingInterval: null,
  starting: false,
  stopping: false,
  showStartModal: false,
  options: {
    use_system_llm: true,
    llm_model_spec: '',
    test_mode: false,
    max_papers: 100,
    clear_db: true
  }
})

const systemDefaultModel = computed(() => configStore.config?.default_model || '')

const effectiveLlmSpec = computed(() => {
  if (state.options.use_system_llm) {
    return systemDefaultModel.value || ''
  }
  return state.options.llm_model_spec || ''
})

const statusLabel = computed(() => {
  const status = state.currentBuild?.status || 'idle'
  switch (status) {
    case 'running':
      return 'Construction in Progress'
    case 'completed':
      return 'Build Completed'
    case 'failed':
      return 'Build Failed'
    case 'stopped':
      return 'Build Stopped'
    case 'idle':
      return 'Ready to Start'
    default:
      return status.charAt(0).toUpperCase() + status.slice(1)
  }
})

const statusColor = computed(() => {
  const status = state.currentBuild?.status || 'idle'
  switch (status) {
    case 'running':
      return 'blue'
    case 'completed':
      return 'success'
    case 'failed':
      return 'error'
    case 'stopped':
      return 'warning'
    default:
      return 'default'
  }
})

const progressStatus = computed(() => {
  const status = state.currentBuild?.status || 'idle'
  if (status === 'failed') return 'exception'
  if (status === 'completed') return 'success'
  if (status === 'running') return 'active'
  return 'normal'
})

const isRunning = computed(() => state.currentBuild?.status === 'running')

const fetchStatus = async () => {
  try {
    const res = await unifiedApi.getKgStatus()
    if (res.success) {
      state.currentBuild = res.data.current
      state.history = res.data.history

      // Stop polling if not running and not just started
      if (!isRunning.value && state.pollingInterval) {
        // We might want to keep polling for a few cycles after completion
        // to show the 100% state
      }
    }
  } catch (error) {
    console.error('Failed to fetch KG status:', error)
  }
}

const handleLlmSelect = (spec) => {
  if (typeof spec === 'string' && spec) {
    state.options.llm_model_spec = spec
  }
}

const openStartModal = async () => {
  if (!configStore.config?.default_model) {
    try {
      await configStore.refreshConfig()
    } catch (error) {
      console.warn('Failed to refresh system config before opening KG build modal:', error)
    }
  }

  if (!state.options.llm_model_spec && systemDefaultModel.value) {
    state.options.llm_model_spec = systemDefaultModel.value
  }

  state.showStartModal = true
}

const startBuild = async () => {
  if (!effectiveLlmSpec.value) {
    message.error('Please configure an LLM model before starting KG build.')
    return
  }

  state.starting = true
  try {
    const payload = {
      test_mode: state.options.test_mode,
      max_papers: state.options.test_mode ? null : state.options.max_papers,
      clear_db: state.options.clear_db,
      llm_model_spec: effectiveLlmSpec.value
    }

    const res = await unifiedApi.buildKg(payload)
    if (res.success) {
      message.success(res.message || 'Build started successfully')
      state.showStartModal = false
      await fetchStatus()
      startPolling()
    } else {
      message.error(res.error || 'Failed to start build')
    }
  } catch (error) {
    message.error('Error starting build: ' + error.message)
  } finally {
    state.starting = false
  }
}

const stopBuild = async () => {
  state.stopping = true
  try {
    const res = await unifiedApi.stopKgBuild()
    if (res.success) {
      message.info(res.message || 'Stop request sent')
      await fetchStatus()
    }
  } catch (error) {
    message.error('Error stopping build: ' + error.message)
  } finally {
    state.stopping = false
  }
}

const startPolling = () => {
  if (state.pollingInterval) clearInterval(state.pollingInterval)
  state.pollingInterval = setInterval(fetchStatus, 3000)
}

const formatTime = (timeStr) => {
  if (!timeStr) return '-'
  return dayjs(timeStr).format('YYYY-MM-DD HH:mm:ss')
}

const formatDuration = (seconds) => {
  if (!seconds) return '0s'
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins > 0) return `${mins}m ${secs}s`
  return `${secs}s`
}

onMounted(() => {
  if (!configStore.config?.default_model) {
    configStore.refreshConfig().catch((error) => {
      console.warn('Failed to load system config for KG Builder:', error)
    })
  }
  fetchStatus()
  startPolling()
})

onUnmounted(() => {
  if (state.pollingInterval) clearInterval(state.pollingInterval)
})
</script>

<style lang="less" scoped>
.kg-builder {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 4px;

  .active-build-card {
    background: linear-gradient(135deg, var(--gray-0) 0%, var(--primary-50) 100%);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    border-radius: 12px;

    :deep(.ant-card-head) {
      border-bottom: 1px dashed rgba(0, 0, 0, 0.1);
    }
  }

  .build-progress {
    margin: 16px 0;

    .progress-message {
      margin-top: 12px;
      font-size: 14px;
      color: var(--color-text-secondary);
      font-weight: 500;
    }
  }

  .build-metrics {
    display: flex;
    gap: 24px;
    margin-bottom: 20px;
    padding: 12px;
    background: rgba(255, 255, 255, 0.5);
    border-radius: 8px;

    .metric-item {
      display: flex;
      flex-direction: column;

      .label {
        font-size: 12px;
        color: var(--color-text-quaternary);
        text-transform: uppercase;
      }

      .value {
        font-size: 14px;
        color: var(--color-text);
        font-weight: 500;
      }
    }
  }

  .build-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
  }

  .build-error-alert {
    margin-top: 16px;
  }

  .section-title {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 12px;
    color: var(--color-text);
  }

  .build-history {
    .history-bullet {
      width: 10px;
      height: 10px;
      border-radius: 50%;

      &.completed {
        background-color: var(--color-success-500);
      }
      &.failed {
        background-color: var(--color-error-500);
      }
      &.stopped {
        background-color: var(--color-warning-500);
      }
      &.running {
        background-color: var(--color-primary-500);
      }
    }
  }
}
</style>
