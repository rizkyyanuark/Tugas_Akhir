<template>
  <a-modal
    v-model:open="showModal"
    title="Debug Panel (Use with caution in production)"
    width="90%"
    :footer="null"
    :maskClosable="true"
    :destroyOnClose="true"
    class="debug-modal-container"
  >
    <div :class="['log-viewer', { fullscreen: state.isFullscreen }]" ref="logViewer">
      <div class="control-panel">
        <div class="button-group">
          <a-tooltip title="Reload logs">
            <a-button
              @click="fetchLogs"
              :loading="state.fetching"
              :icon="h(ReloadOutlined)"
              class="icon-only"
            />
          </a-tooltip>
          <a-tooltip title="Clear log viewer">
            <a-button @click="clearLogs" :icon="h(ClearOutlined)" class="icon-only" />
          </a-tooltip>
          <a-tooltip title="Copy logs to clipboard">
            <a-button @click="copyLogs" :icon="h(CopyOutlined)" class="icon-only" />
          </a-tooltip>
          <a-button @click="printSystemConfig">
            <template #icon><SettingOutlined /></template>
            System Config
          </a-button>
          <a-button @click="printUserInfo">
            <template #icon><UserOutlined /></template>
            User Info
          </a-button>
          <a-button @click="printDatabaseInfo">
            <template #icon><DatabaseOutlined /></template>
            Knowledge Base Info
          </a-button>
          <a-button @click="printAgentConfig">
            <template #icon><RobotOutlined /></template>
            Agent Config
          </a-button>
          <a-button @click="toggleDebugMode" :type="infoStore.debugMode ? 'primary' : 'default'">
            <template #icon><BugOutlined /></template>
            Debug Mode: {{ infoStore.debugMode ? 'On' : 'Off' }}
          </a-button>
          <a-button @click="toggleFullscreen">
            <template #icon>
              <FullscreenOutlined v-if="!state.isFullscreen" />
              <FullscreenExitOutlined v-else />
            </template>
            {{ state.isFullscreen ? 'Exit Fullscreen' : 'Fullscreen' }}
          </a-button>
          <a-tooltip
            :title="
              state.autoRefresh ? 'Click to stop auto-refresh' : 'Click to start auto-refresh'
            "
          >
            <a-button
              :type="state.autoRefresh ? 'primary' : 'default'"
              :class="{ 'auto-refresh-button': state.autoRefresh }"
              @click="toggleAutoRefresh(!state.autoRefresh)"
            >
              <template #icon>
                <SyncOutlined :spin="state.autoRefresh" />
              </template>
              Auto Refresh
              <span v-if="state.autoRefresh" class="refresh-interval">(5s)</span>
            </a-button>
          </a-tooltip>
          <a-button @click="openUserSwitcher">
            <template #icon><SwapOutlined /></template>
            Switch User
          </a-button>
        </div>
        <div class="filter-group">
          <a-input-search
            v-model:value="state.searchText"
            placeholder="Search logs..."
            style="width: 220px; height: 32px"
            @search="onSearch"
          />
          <div class="log-level-selector">
            <div class="multi-select-cards">
              <div
                v-for="level in logLevels"
                :key="level.value"
                class="option-card"
                :class="{
                  selected: isLogLevelSelected(level.value),
                  unselected: !isLogLevelSelected(level.value),
                  [`badge-${level.value.toLowerCase()}`]: true
                }"
                @click="toggleLogLevel(level.value)"
              >
                <div class="option-content">
                  <span class="option-text">{{ level.label }}</span>
                  <div class="option-indicator">
                    <CheckCircleOutlined v-if="isLogLevelSelected(level.value)" />
                    <PlusCircleOutlined v-else />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div ref="logContainer" class="log-container">
        <div v-if="processedLogs.length" class="log-lines">
          <div
            v-for="(log, index) in processedLogs"
            :key="index"
            :class="['log-line', `level-${log.level.toLowerCase()}`]"
          >
            <span class="timestamp">{{ formatTimestamp(log.timestamp) }}</span>
            <span class="level-badge">{{ log.level }}</span>
            <span v-if="log.module" class="module">{{ log.module }}</span>
            <span class="message" v-html="highlightSearchText(log.message)"></span>
          </div>
        </div>
        <div v-else class="empty-logs">No logs found</div>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <!-- User switcher modal -->
      <a-modal
        v-model:open="state.showUserSwitcher"
        title="Switch User"
        :confirmLoading="state.switchingUser"
        :footer="null"
        :bodyStyle="{ padding: '12px' }"
      >
        <a-list item-layout="horizontal" :data-source="state.users">
          <template #renderItem="{ item }">
            <a-list-item @click="switchToUser(item)" style="cursor: pointer">
              <a-list-item-meta :title="item.username" :description="item.role" />
            </a-list-item>
          </template>
          <template #empty>
            <a-empty description="No users" />
          </template>
        </a-list>
      </a-modal>
    </div>
  </a-modal>
</template>

<script setup>
import {
  ref,
  reactive,
  computed,
  onMounted,
  onActivated,
  onUnmounted,
  nextTick,
  toRaw,
  h,
  watch
} from 'vue'

const showModal = defineModel('show')

// Watch showModal changes and fetch logs when opened
watch(showModal, (isOpen) => {
  if (isOpen) {
    setTimeout(fetchLogs, 100)
  }
})

import { useConfigStore } from '@/stores/config'
import { useUserStore } from '@/stores/user'
import { useDatabaseStore } from '@/stores/database'
import { useAgentStore } from '@/stores/agent'
import { useInfoStore } from '@/stores/info'
import { useThrottleFn } from '@vueuse/core'
import {
  message,
  Modal,
  List as AList,
  ListItem as AListItem,
  ListItemMeta as AListItemMeta,
  Empty as AEmpty
} from 'ant-design-vue'
import {
  FullscreenOutlined,
  FullscreenExitOutlined,
  ReloadOutlined,
  ClearOutlined,
  CopyOutlined,
  SettingOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  PlusCircleOutlined,
  UserOutlined,
  DatabaseOutlined,
  RobotOutlined,
  BugOutlined,
  SwapOutlined
} from '@ant-design/icons-vue'
import dayjs from '@/utils/time'
import { configApi } from '@/apis/system_api'
import { checkSuperAdminPermission } from '@/stores/user'

const configStore = useConfigStore()
const userStore = useUserStore()
const databaseStore = useDatabaseStore()
const agentStore = useAgentStore()
const infoStore = useInfoStore()
const config = configStore.config

// Define log levels
const logLevels = [
  { value: 'INFO', label: 'INFO' },
  { value: 'ERROR', label: 'ERROR' },
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'WARNING', label: 'WARNING' }
]

const logViewer = ref(null)

// State management
const state = reactive({
  fetching: false,
  autoRefresh: false,
  searchText: '',
  selectedLevels: logLevels.map((l) => l.value),
  rawLogs: [],
  isFullscreen: false,
  showUserSwitcher: false,
  users: [],
  switchingUser: false
})

const error = ref('')
const logContainer = ref(null)
let autoRefreshInterval = null

// Parse a log line
const parseLogLine = (line) => {
  if (!line || !line.trim()) return null

  // Support timestamp formats: 2026-07-31 10:32:48,314 or 2026-07-31 10:32:48
  const match = line.match(
    /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[,\.]\d{3})?)\s*[-:]?\s*(\w+)\s*[-:]?\s*([^-:]+?)?\s*[-:]?\s*(.+)$/
  )
  if (match) {
    return {
      timestamp: match[1],
      level: match[2].toUpperCase(),
      module: (match[3] || '').trim(),
      message: match[4].trim(),
      raw: line
    }
  }

  // Fallback for stack traces or unformatted lines so they are NOT lost
  return {
    timestamp: '',
    level: 'INFO',
    module: '',
    message: line,
    raw: line
  }
}

// Format timestamp
const formatTimestamp = (timestamp) => {
  if (!timestamp) return ''
  try {
    let normalizedTimestamp = timestamp.replace(',', '.')
    if (!/\.\d{3}$/.test(normalizedTimestamp)) {
      normalizedTimestamp += '.000'
    }
    const date = dayjs(normalizedTimestamp)
    return date.isValid() ? date.format('HH:mm:ss.SSS') : timestamp
  } catch (err) {
    return timestamp
  }
}

// Process logs for display
const processedLogs = computed(() => {
  return state.rawLogs
    .map(parseLogLine)
    .filter((log) => log !== null)
    .filter((log) => {
      if (!state.searchText) return true
      return log.raw.toLowerCase().includes(state.searchText.toLowerCase())
    })
})

// Highlight search text inside log message
const highlightSearchText = (text) => {
  if (!text) return ''
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  if (!state.searchText || !state.searchText.trim()) {
    return escaped
  }

  const query = state.searchText.trim()
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return escaped.replace(regex, '<mark class="log-highlight">$1</mark>')
}

// Fetch logs
const fetchLogs = async () => {
  if (!checkSuperAdminPermission()) return

  state.fetching = true
  try {
    error.value = ''
    const levelsParam = state.selectedLevels.join(',')
    const logData = await configApi.getLogs(levelsParam)
    state.rawLogs = (logData.log || '').split('\n').filter((line) => line.trim())

    await nextTick()
    const scrollToBottom = useThrottleFn(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    }, 100)
    scrollToBottom()
  } catch (err) {
    error.value = `Error: ${err.message}`
  } finally {
    state.fetching = false
  }
}

// Clear logs
const clearLogs = () => {
  if (!checkSuperAdminPermission()) return
  state.rawLogs = []
}

// Copy logs
const copyLogs = async () => {
  const logText = processedLogs.value.map((l) => l.raw).join('\n')
  if (!logText) {
    message.warning('No logs to copy')
    return
  }
  try {
    await navigator.clipboard.writeText(logText)
    message.success(`Copied ${processedLogs.value.length} log lines to clipboard`)
  } catch (err) {
    message.error('Failed to copy logs to clipboard')
  }
}

// Search feature
const onSearch = () => {
  // Search is handled automatically by computed state
}

// Log level selection helpers
const isLogLevelSelected = (level) => {
  return state.selectedLevels.includes(level)
}

const toggleLogLevel = (level) => {
  const currentLevels = [...state.selectedLevels]
  const index = currentLevels.indexOf(level)

  if (index > -1) {
    if (currentLevels.length === 1) return
    currentLevels.splice(index, 1)
  } else {
    currentLevels.push(level)
  }

  state.selectedLevels = currentLevels
  fetchLogs()
}

// Auto refresh
const toggleAutoRefresh = (value) => {
  if (!checkSuperAdminPermission()) return

  if (value) {
    autoRefreshInterval = setInterval(fetchLogs, 5000)
    state.autoRefresh = true
  } else {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval)
      autoRefreshInterval = null
    }
    state.autoRefresh = false
  }
}

// Toggle fullscreen
const toggleFullscreen = async () => {
  if (!checkSuperAdminPermission()) return

  try {
    if (!state.isFullscreen) {
      if (logViewer.value.requestFullscreen) {
        await logViewer.value.requestFullscreen()
      } else if (logViewer.value.webkitRequestFullscreen) {
        await logViewer.value.webkitRequestFullscreen()
      } else if (logViewer.value.msRequestFullscreen) {
        await logViewer.value.msRequestFullscreen()
      }
    } else {
      if (document.exitFullscreen) {
        await document.exitFullscreen()
      } else if (document.webkitExitFullscreen) {
        await document.webkitExitFullscreen()
      } else if (document.msExitFullscreen) {
        await document.msExitFullscreen()
      }
    }
  } catch (err) {
    console.error('Failed to toggle fullscreen:', err)
  }
}

// Watch fullscreen changes
const handleFullscreenChange = () => {
  state.isFullscreen = Boolean(
    document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement
  )
}

onMounted(() => {
  document.addEventListener('fullscreenchange', handleFullscreenChange)
  document.addEventListener('webkitfullscreenchange', handleFullscreenChange)
  document.addEventListener('msfullscreenchange', handleFullscreenChange)
})

onActivated(() => {
  if (state.autoRefresh) {
    toggleAutoRefresh(true)
  } else if (showModal.value) {
    fetchLogs()
  }
})

onUnmounted(() => {
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval)
    autoRefreshInterval = null
  }
  document.removeEventListener('fullscreenchange', handleFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', handleFullscreenChange)
  document.removeEventListener('msfullscreenchange', handleFullscreenChange)
})

// Print system config
const printSystemConfig = () => {
  if (!checkSuperAdminPermission()) return
  console.log('=== System Config ===')
  console.log(config)
}

// Print user info
const printUserInfo = () => {
  if (!checkSuperAdminPermission()) return
  console.log('=== User Info ===')
  const userInfo = {
    token: userStore.token ? '*** (hidden)' : null,
    userId: userStore.userId,
    username: userStore.username,
    userIdLogin: userStore.userIdLogin,
    phoneNumber: userStore.phoneNumber,
    avatar: userStore.avatar,
    userRole: userStore.userRole,
    isLoggedIn: userStore.isLoggedIn,
    isAdmin: userStore.isAdmin,
    isSuperAdmin: userStore.isSuperAdmin
  }
  console.log(JSON.stringify(userInfo, null, 2))
}

// Print knowledge base info
const printDatabaseInfo = async () => {
  if (!checkSuperAdminPermission()) return

  try {
    console.log('=== Knowledge Base Info ===')
    console.log('Basic info:', {
      databaseId: databaseStore.databaseId,
      databaseName: databaseStore.database.name,
      databaseDesc: databaseStore.database.description,
      fileCount: Object.keys(databaseStore.database.files || {}).length
    })

    console.log('State info:', {
      databaseLoading: databaseStore.state.databaseLoading,
      refrashing: databaseStore.state.refrashing,
      searchLoading: databaseStore.state.searchLoading,
      lock: databaseStore.state.lock,
      autoRefresh: databaseStore.state.autoRefresh,
      queryParamsLoading: databaseStore.state.queryParamsLoading
    })

    console.log('Query params:', {
      queryParams: databaseStore.queryParams,
      meta: databaseStore.meta,
      selectedFileCount: databaseStore.selectedRowKeys.length
    })
  } catch (error) {
    console.error('Failed to get knowledge base info:', error)
    message.error('Failed to get knowledge base info: ' + error.message)
  }
}

// Toggle debug mode
const toggleDebugMode = () => {
  if (!checkSuperAdminPermission()) return
  infoStore.toggleDebugMode()
}

// Print agent config
const printAgentConfig = async () => {
  if (!checkSuperAdminPermission()) return

  try {
    console.log('=== Agent Config Info ===')

    console.log('Store state:', {
      isInitialized: agentStore.isInitialized,
      selectedAgentId: agentStore.selectedAgentId,
      defaultAgentId: agentStore.defaultAgentId,
      agentCount: agentStore.agentsList.length,
      loadingStates: {
        isLoadingAgents: agentStore.isLoadingAgents,
        isLoadingConfig: agentStore.isLoadingConfig,
        isLoadingTools: agentStore.isLoadingTools
      },
      error: agentStore.error,
      hasConfigChanges: agentStore.hasConfigChanges
    })

    console.log('Agent list:', {
      count: agentStore.agentsList.length,
      agents: toRaw(agentStore.agentsList)
    })

    if (agentStore.selectedAgent) {
      console.log('Current selected agent:', {
        agent: toRaw(agentStore.selectedAgent),
        isDefault: agentStore.isDefaultAgent,
        configurableItemsCount: Object.keys(agentStore.configurableItems).length
      })

      if (userStore.isAdmin) {
        console.log('Current agent config:', {
          current: toRaw(agentStore.agentConfig),
          original: toRaw(agentStore.originalAgentConfig),
          hasChanges: agentStore.hasConfigChanges
        })
      } else {
        console.log('Agent config: admin permission required for details')
      }
    }

    const toolsList = agentStore.availableTools ? Object.values(agentStore.availableTools) : []
    console.log('Available tools:', {
      count: toolsList.length,
      tools: toolsList
    })

    if (userStore.isAdmin && agentStore.selectedAgent) {
      console.log('Configurable items:', toRaw(agentStore.configurableItems))
    }
  } catch (error) {
    console.error('Failed to get agent config:', error)
    message.error('Failed to get agent config: ' + error.message)
  }
}

// Fetch user list
const fetchUsers = async () => {
  try {
    const response = await fetch('/api/auth/users', {
      headers: userStore.getAuthHeaders()
    })
    if (!response.ok) {
      throw new Error('Failed to fetch user list')
    }
    state.users = await response.json()
  } catch (err) {
    message.error(`Failed to fetch user list: ${err.message}`)
  }
}

// Open user switcher
const openUserSwitcher = () => {
  if (!checkSuperAdminPermission()) return
  state.showUserSwitcher = true
  fetchUsers()
}

// Switch user
const switchToUser = async (user) => {
  if (!checkSuperAdminPermission()) return

  Modal.confirm({
    title: 'Dangerous Operation Confirmation',
    content: `Are you sure you want to switch to user "${user.username}"? This action will be logged.`,
    okText: 'Confirm Switch',
    cancelText: 'Cancel',
    okType: 'danger',
    onOk: async () => {
      state.switchingUser = true
      try {
        const response = await fetch(`/api/auth/impersonate/${user.id}`, {
          method: 'POST',
          headers: userStore.getAuthHeaders()
        })
        if (!response.ok) {
          const error = await response.json()
          throw new Error(error.detail || 'Failed to switch user')
        }
        const data = await response.json()
        localStorage.setItem('user_token', data.access_token)
        message.success(`Switched user: ${user.username}`)
        state.showUserSwitcher = false
        window.location.reload()
      } catch (err) {
        message.error(`Switch failed: ${err.message}`)
      } finally {
        state.switchingUser = false
      }
    }
  })
}
</script>

<style scoped lang="less">
.log-viewer.fullscreen {
  padding: 16px;
}

.control-panel {
  margin-bottom: 16px;
}

.button-group {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;

  .ant-btn {
    min-width: 80px;
    height: 32px;
    padding: 4px 12px;
    font-size: 13px;
    border-color: var(--gray-300);
    color: var(--gray-700);

    &.icon-only {
      min-width: 32px;
      padding: 0;
    }

    &:hover {
      border-color: var(--main-color);
      color: var(--main-color);
    }

    &.ant-btn-primary {
      background-color: var(--main-color);
      border-color: var(--main-color);
      color: #ffffff;
    }
  }

  .refresh-interval {
    font-size: 12px;
    opacity: 0.8;
    margin-left: 2px;
  }
}

.filter-group {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}

.error {
  color: #f87171;
  margin-top: 8px;
  font-weight: 500;
}

/* Dedicated High-Contrast Terminal Dark Canvas */
.log-container {
  height: calc(80vh - 200px);
  overflow-y: auto;
  background-color: #0d1117 !important; /* GitHub/VSCode Dark Terminal Canvas */
  color: #f8fafc !important; /* Crisp Bright Slate White Text */
  border-radius: 8px;
  border: 1px solid #1e293b;
  font-family: 'Fira Code', 'Consolas', 'JetBrains Mono', 'Monaco', monospace;
  font-size: 12.5px;
  letter-spacing: 0.2px;
  box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.4);
}

/* Custom Sleek Scrollbar */
.log-container::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.log-container::-webkit-scrollbar-track {
  background: #090d13;
}

.log-container::-webkit-scrollbar-thumb {
  background: #334155;
  border-radius: 4px;
}

.log-container::-webkit-scrollbar-thumb:hover {
  background: #475569;
}

.log-lines {
  padding: 10px 12px;
}

.log-line {
  padding: 3px 6px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  line-height: 1.55;
  border-radius: 4px;
  transition: background 0.15s ease;

  &:hover {
    background-color: rgba(255, 255, 255, 0.08) !important;
  }
}

/* High Contrast Log Field Styling */
.timestamp {
  color: #64748b !important; /* Muted Slate Gray */
  font-size: 11.5px;
  white-space: nowrap;
  user-select: none;
}

.level-badge {
  font-weight: 700;
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
  user-select: none;
}

.module {
  color: #38bdf8 !important; /* Sky Blue Module Name */
  font-weight: 500;
  white-space: nowrap;
  opacity: 0.9;
}

.message {
  flex: 1;
  color: #f8fafc !important; /* Explicit 100% Crisp White Message Text */
  white-space: pre-wrap;
  word-break: break-all;
}

/* Log Level Badges & Message Color Highlights */
.level-info {
  .level-badge {
    background-color: rgba(16, 185, 129, 0.2);
    color: #34d399 !important;
    border: 1px solid rgba(16, 185, 129, 0.4);
  }
}

.level-warning {
  .level-badge {
    background-color: rgba(245, 158, 11, 0.2);
    color: #fbbf24 !important;
    border: 1px solid rgba(245, 158, 11, 0.4);
  }
  .message {
    color: #fef08a !important;
  }
}

.level-error {
  .level-badge {
    background-color: rgba(239, 68, 68, 0.25);
    color: #f87171 !important;
    border: 1px solid rgba(239, 68, 68, 0.5);
  }
  .message {
    color: #fca5a5 !important;
  }
}

.level-debug {
  .level-badge {
    background-color: rgba(168, 85, 247, 0.2);
    color: #c084fc !important;
    border: 1px solid rgba(168, 85, 247, 0.4);
  }
}

:deep(.log-highlight) {
  background-color: #0284c7 !important;
  color: #ffffff !important;
  padding: 0 3px;
  border-radius: 2px;
  font-weight: 600;
}

.empty-logs {
  padding: 32px;
  text-align: center;
  color: #64748b !important;
  font-size: 13px;
}

:fullscreen .log-container {
  height: calc(100vh - 160px);
}

.multi-select-cards {
  display: flex;
  flex-direction: row;
  gap: 8px;

  .option-card {
    border: 1px solid var(--gray-300);
    border-radius: 6px;
    padding: 0 10px;
    cursor: pointer;
    transition: all 0.2s ease;
    background: var(--gray-0);
    user-select: none;
    height: 32px;
    display: flex;
    align-items: center;

    &:hover {
      border-color: var(--main-color);
      background: var(--main-5);
    }

    &.selected {
      border-color: var(--main-color);
      background: var(--main-10);

      .option-indicator {
        color: var(--main-color);
      }

      .option-text {
        color: var(--main-color);
        font-weight: 600;
      }
    }

    &.unselected {
      opacity: 0.6;
      .option-indicator {
        color: var(--gray-400);
      }
      .option-text {
        color: var(--gray-700);
      }
    }

    .option-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 6px;
      width: 100%;
    }

    .option-text {
      flex: 1;
      font-size: 12px;
      text-align: center;
    }

    .option-indicator {
      flex-shrink: 0;
      font-size: 13px;
    }
  }
}
</style>
