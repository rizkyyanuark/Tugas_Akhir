<template>
  <div class="mcp-servers extension-page-root">
    <div v-if="loading" class="loading-bar-wrapper">
      <div class="loading-bar"></div>
    </div>
    <div class="layout-wrapper" :class="{ 'content-loading': loading }">
      <!-- Left: MCP list -->
      <div class="sidebar-list">
        <!-- Search box -->
        <div class="sidebar-toolbar">
          <div class="search-box">
            <a-input
              v-model:value="searchQuery"
              placeholder="Search MCP..."
              allow-clear
              class="search-input"
            >
              <template #prefix><Search :size="14" class="text-muted" /></template>
            </a-input>
          </div>

          <a-tooltip title="Refresh MCP">
            <a-button class="sidebar-tool" :disabled="loading" @click="fetchServers">
              <RotateCw :size="14" />
            </a-button>
          </a-tooltip>
        </div>

        <!-- Statistics -->
        <!-- <div class="stats-section" v-if="filteredServers.length > 0">
          <span class="stats-text">
            {{ filteredServers.length }} MCPs: HTTP: {{ httpCount }} · SSE: {{ sseCount }} · StdIO: {{ stdioCount }}
          </span>
        </div> -->

        <!-- MCP list -->
        <div class="list-container">
          <div
            v-if="!filteredEnabledServers.length && !filteredDisabledServers.length"
            class="empty-text"
          >
            <a-empty
              :image="false"
              :description="searchQuery ? 'No matching MCPs' : 'No MCPs yet'"
            />
          </div>
          <div v-if="filteredEnabledServers.length" class="list-section-title">Added</div>
          <template
            v-for="(server, index) in filteredEnabledServers"
            :key="`enabled-${server.name}`"
          >
            <div
              class="list-item extension-list-item"
              :class="{ active: currentServer?.name === server.name }"
              @click="selectServer(server)"
            >
              <div class="item-main-row">
                <div class="item-header">
                  <span class="server-icon">{{ server.icon || '🔌' }}</span>
                  <span class="item-name">{{ server.name }}</span>
                </div>
                <div class="item-status">
                  <span class="status-chip status-chip-success">Added</span>
                  <button
                    type="button"
                    class="inline-hover-action"
                    @click.stop="handleInlineRemoveServer(server)"
                  >
                    {{ getServerActionLabel(server) }}
                  </button>
                </div>
              </div>
              <div class="item-details">
                <span class="item-desc">{{
                  server.description || 'No description available'
                }}</span>
                <div class="item-tags">
                  <span v-if="server.created_by === 'system'" class="source-tag builtin"
                    >Built-in</span
                  >
                </div>
              </div>
            </div>
            <div
              v-if="index < filteredEnabledServers.length - 1 || filteredDisabledServers.length > 0"
              class="list-separator"
            ></div>
          </template>
          <div v-if="filteredDisabledServers.length" class="list-section-title">Available</div>
          <template
            v-for="(server, index) in filteredDisabledServers"
            :key="`disabled-${server.name}`"
          >
            <div
              class="list-item extension-list-item"
              :class="{ active: currentServer?.name === server.name, disabled: true }"
              @click="selectServer(server)"
            >
              <div class="item-main-row">
                <div class="item-header">
                  <span class="server-icon">{{ server.icon || '🔌' }}</span>
                  <span class="item-name">{{ server.name }}</span>
                </div>
                <div class="item-status">
                  <button
                    type="button"
                    class="skill-inline-action skill-inline-action-primary"
                    @click.stop="handleSetServerEnabled(server, true)"
                  >
                    Add
                  </button>
                </div>
              </div>
              <div class="item-details">
                <span class="item-desc">{{
                  server.description || 'No description available'
                }}</span>
                <div class="item-tags">
                  <span v-if="server.created_by === 'system'" class="source-tag builtin"
                    >Built-in</span
                  >
                </div>
              </div>
            </div>
            <div v-if="index < filteredDisabledServers.length - 1" class="list-separator"></div>
          </template>
        </div>
      </div>

      <!-- Right: detail panel -->
      <div class="main-panel">
        <div v-if="!currentServer" class="unselected-state">
          <div class="hint-box">
            <Plug :size="40" class="text-muted" />
            <p>Select an MCP from the left panel to manage</p>
          </div>
        </div>

        <template v-else>
          <div class="panel-top-bar">
            <h2 class="panel-title-row">
              <span class="server-icon-lg">{{ currentServer.icon || '🔌' }}</span>
              <span
                ><strong>{{ currentServer.name }}</strong></span
              >
            </h2>
            <div class="panel-actions">
              <a-space :size="8">
                <button
                  type="button"
                  @click="handleTestServer(currentServer)"
                  :disabled="testLoading === currentServer.name"
                  class="lucide-icon-btn extension-panel-action extension-panel-action-secondary"
                >
                  <Zap :size="14" v-if="testLoading !== currentServer.name" />
                  <span>Test</span>
                </button>
                <button
                  type="button"
                  @click="showEditModal(currentServer)"
                  class="lucide-icon-btn extension-panel-action extension-panel-action-secondary"
                >
                  <Pencil :size="14" />
                  <span>Edit</span>
                </button>
                <button
                  type="button"
                  @click="handleDangerAction(currentServer)"
                  :class="[
                    'lucide-icon-btn',
                    'extension-panel-action',
                    getServerActionTone(currentServer)
                  ]"
                >
                  <Plus v-if="currentServer.enabled === false" :size="14" />
                  <Trash2 v-else :size="14" />
                  <span>{{ getServerActionLabel(currentServer) }}</span>
                </button>
              </a-space>
            </div>
          </div>

          <!-- Tab navigation -->
          <a-tabs v-model:activeKey="detailTab" class="detail-tabs">
            <a-tab-pane key="general">
              <template #tab>
                <span class="tab-title"><Settings2 :size="14" />Information</span>
              </template>
              <div class="tab-content">
                <div class="info-grid">
                  <div class="info-item" v-if="currentServer.description">
                    <label>Description</label>
                    <span>{{ currentServer.description }}</span>
                  </div>
                  <div class="info-item">
                    <label>Transport Type</label>
                    <span>
                      <a-tag :color="getTransportColor(currentServer.transport)">
                        {{ currentServer.transport }}
                      </a-tag>
                    </span>
                  </div>
                  <div
                    class="info-item"
                    v-if="Array.isArray(currentServer.tags) && currentServer.tags.length > 0"
                  >
                    <label>Tags</label>
                    <span>
                      <a-tag v-for="tag in currentServer.tags" :key="tag">{{ tag }}</a-tag>
                    </span>
                  </div>

                  <!-- Show URL for HTTP/SSE transport -->
                  <template
                    v-if="
                      currentServer.transport === 'streamable_http' ||
                      currentServer.transport === 'sse'
                    "
                  >
                    <div class="info-item" v-if="currentServer.url">
                      <label>MCP URL</label>
                      <span class="code-inline text-break-all">{{ currentServer.url }}</span>
                    </div>
                    <div
                      class="info-item"
                      v-if="currentServer.headers && Object.keys(currentServer.headers).length > 0"
                    >
                      <label>Request Headers</label>
                      <pre class="code-pre">{{
                        JSON.stringify(currentServer.headers, null, 2)
                      }}</pre>
                    </div>
                    <div class="info-item" v-if="currentServer.timeout">
                      <label>HTTP Timeout</label>
                      <span>{{ currentServer.timeout }} s</span>
                    </div>
                    <div class="info-item" v-if="currentServer.sse_read_timeout">
                      <label>SSE Read Timeout</label>
                      <span>{{ currentServer.sse_read_timeout }} s</span>
                    </div>
                  </template>

                  <!-- Show command/args for StdIO transport -->
                  <template v-if="currentServer.transport === 'stdio'">
                    <div class="info-item" v-if="currentServer.command">
                      <label>Command</label>
                      <span class="code-inline">{{ currentServer.command }}</span>
                    </div>
                    <div
                      class="info-item"
                      v-if="currentServer.args && currentServer.args.length > 0"
                    >
                      <label>Arguments</label>
                      <span>
                        <a-tag v-for="(arg, index) in currentServer.args" :key="index" size="small">
                          {{ arg }}
                        </a-tag>
                      </span>
                    </div>
                    <div
                      class="info-item"
                      v-if="currentServer.env && Object.keys(currentServer.env).length > 0"
                    >
                      <label>Environment Variables</label>
                      <pre class="code-pre">{{ JSON.stringify(currentServer.env, null, 2) }}</pre>
                    </div>
                  </template>

                  <div class="info-item">
                    <label>Created At</label>
                    <span>{{ formatTime(currentServer.created_at) }}</span>
                  </div>
                  <div class="info-item">
                    <label>Updated At</label>
                    <span>{{ formatTime(currentServer.updated_at) }}</span>
                  </div>
                  <div class="info-item">
                    <label>Created By</label>
                    <span>{{ currentServer.created_by }}</span>
                  </div>
                </div>
              </div>
            </a-tab-pane>

            <a-tab-pane key="tools">
              <template #tab>
                <span class="tab-title"><Wrench :size="14" />Tools ({{ tools.length }})</span>
              </template>
              <div class="tab-content tools-tab">
                <div class="tools-toolbar">
                  <a-input-search
                    v-model:value="toolSearchText"
                    placeholder="Search tools..."
                    style="width: 200px"
                    allowClear
                  />
                  <a-button @click="fetchTools" :loading="toolsLoading" class="lucide-icon-btn">
                    <RotateCw :size="14" />
                    <span>Refresh</span>
                  </a-button>
                </div>
                <a-spin :spinning="toolsLoading">
                  <div v-if="filteredTools.length === 0" class="empty-tools">
                    <a-empty :description="toolsError || 'No tools available'" />
                  </div>
                  <div v-else class="tools-list">
                    <div
                      v-for="tool in filteredTools"
                      :key="tool.name"
                      class="tool-card"
                      :class="{ disabled: !tool.enabled }"
                    >
                      <div class="tool-header">
                        <div class="tool-info">
                          <span class="tool-name">{{ tool.name }}</span>
                          <a-tooltip :title="`ID: ${tool.id}`">
                            <Info :size="14" class="info-icon" />
                          </a-tooltip>
                        </div>
                        <div class="tool-actions">
                          <a-switch
                            :checked="tool.enabled"
                            @change="handleToggleTool(tool)"
                            :loading="toggleToolLoading === tool.name"
                            size="small"
                          />
                          <a-tooltip title="Copy tool name">
                            <a-button
                              type="text"
                              size="small"
                              @click="copyToolName(tool.name)"
                              class="lucide-icon-btn"
                            >
                              <Copy :size="14" />
                            </a-button>
                          </a-tooltip>
                        </div>
                      </div>
                      <div class="tool-description" v-if="tool.description">
                        {{ tool.description }}
                      </div>
                      <a-collapse
                        v-if="tool.parameters && Object.keys(tool.parameters).length > 0"
                        ghost
                      >
                        <a-collapse-panel key="params" header="Arguments">
                          <div class="params-list">
                            <div
                              v-for="(param, paramName) in tool.parameters"
                              :key="paramName"
                              class="param-item"
                            >
                              <div class="param-header">
                                <span class="param-name">{{ paramName }}</span>
                                <span
                                  class="param-required"
                                  v-if="tool.required?.includes(paramName)"
                                  >Required</span
                                >
                                <span class="param-type">{{ param.type || 'any' }}</span>
                              </div>
                              <div class="param-desc" v-if="param.description">
                                {{ param.description }}
                              </div>
                            </div>
                          </div>
                        </a-collapse-panel>
                      </a-collapse>
                    </div>
                  </div>
                </a-spin>
              </div>
            </a-tab-pane>
          </a-tabs>
        </template>
      </div>
    </div>

    <!-- Add/Edit MCP modal -->
    <a-modal
      v-model:open="formModalVisible"
      :title="editMode ? 'Edit MCP' : 'Add MCP'"
      @ok="handleFormSubmit"
      :confirmLoading="formLoading"
      @cancel="formModalVisible = false"
      :maskClosable="false"
      width="560px"
      class="server-modal"
    >
      <!-- Mode switch -->
      <div class="mode-switch">
        <a-radio-group v-model:value="formMode" button-style="solid" size="small">
          <a-radio-button value="form">Form Mode</a-radio-button>
          <a-radio-button value="json">JSON Mode</a-radio-button>
        </a-radio-group>
      </div>

      <!-- Form Mode -->
      <a-form v-if="formMode === 'form'" layout="vertical" class="extension-form">
        <a-form-item label="MCP Name" required class="form-item">
          <a-input
            v-model:value="form.name"
            placeholder="Enter MCP name (unique identifier)"
            :disabled="editMode"
          />
        </a-form-item>

        <a-form-item label="Description" class="form-item">
          <a-input v-model:value="form.description" placeholder="Enter MCP description" />
        </a-form-item>

        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="Transport Type" required class="form-item">
              <a-select v-model:value="form.transport">
                <a-select-option value="streamable_http">streamable_http</a-select-option>
                <a-select-option value="sse">sse</a-select-option>
                <a-select-option value="stdio">stdio</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="Icon" class="form-item">
              <a-input
                v-model:value="form.icon"
                placeholder="Enter emoji, e.g. 🧠"
                :maxlength="2"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <!-- HTTP/SSE transport fields -->
        <template v-if="form.transport === 'streamable_http' || form.transport === 'sse'">
          <a-form-item label="MCP URL" required class="form-item">
            <a-input v-model:value="form.url" placeholder="https://example.com/mcp" />
          </a-form-item>

          <a-form-item label="HTTP Request Headers" class="form-item">
            <a-textarea
              v-model:value="form.headersText"
              placeholder='JSON format, e.g.:{"Authorization": "Bearer xxx"}'
              :rows="3"
            />
          </a-form-item>

          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item label="HTTP Timeout (s)" class="form-item">
                <a-input-number
                  v-model:value="form.timeout"
                  :min="1"
                  :max="300"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item label="SSE Read Timeout (s)" class="form-item">
                <a-input-number
                  v-model:value="form.sse_read_timeout"
                  :min="1"
                  :max="300"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
          </a-row>
        </template>

        <!-- StdIO transport fields -->
        <template v-if="isStdioTransport">
          <a-form-item label="Command" required class="form-item">
            <a-input
              v-model:value="form.command"
              placeholder="For example: npx or /path/to/server"
            />
          </a-form-item>

          <a-form-item label="Arguments" class="form-item">
            <a-select
              v-model:value="form.args"
              mode="tags"
              placeholder="Enter args and press Enter, e.g. -m"
              style="width: 100%"
            />
          </a-form-item>

          <a-form-item label="Environment Variables" class="form-item">
            <McpEnvEditor v-model="form.env" />
          </a-form-item>
        </template>

        <a-form-item label="Tags" class="form-item">
          <a-select
            v-model:value="form.tags"
            mode="tags"
            placeholder="Enter tags and press Enter"
            style="width: 100%"
          />
        </a-form-item>
      </a-form>

      <!-- JSON Mode -->
      <div v-else class="json-mode">
        <a-textarea
          v-model:value="jsonContent"
          :rows="15"
          placeholder='Enter JSON config, e.g.:
{
  "name": "my-server",
  "transport": "streamable_http",
  "url": "https://example.com/mcp",
  "description": "MCP description",
  "headers": {"Authorization": "Bearer xxx"},
  "tags": ["Tools", "AI"]
}'
          class="json-textarea"
        />
        <div class="json-actions">
          <a-button size="small" @click="formatJson">Format</a-button>
          <a-button size="small" @click="parseJsonToForm">Parse to form</a-button>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  Search,
  Plug,
  Plus,
  Zap,
  Pencil,
  Trash2,
  RotateCw,
  Info,
  Copy,
  Settings2,
  Wrench
} from 'lucide-vue-next'
import { mcpApi } from '@/apis/mcp_api'
import { formatFullDateTime } from '@/utils/time'
import McpEnvEditor from './McpEnvEditor.vue'

// State
const loading = ref(false)
const error = ref(null)
const servers = ref([])
const toggleLoading = ref(null)
const testLoading = ref(null)
const searchQuery = ref('')
const currentServer = ref(null)
const detailTab = ref('general')

// Tools state
const tools = ref([])
const toolsLoading = ref(false)
const toolsError = ref(null)
const toolSearchText = ref('')
const toggleToolLoading = ref(null)

// Form state
const formModalVisible = ref(false)
const formLoading = ref(false)
const formMode = ref('form')
const editMode = ref(false)
const jsonContent = ref('')
const form = reactive({
  name: '',
  description: '',
  transport: 'streamable_http',
  url: '',
  command: '',
  args: [],
  env: null,
  headersText: '',
  timeout: null,
  sse_read_timeout: null,
  tags: [],
  icon: ''
})

// Computed properties
const filteredServers = computed(() => {
  const sorted = [...servers.value].sort((a, b) => {
    return String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN', {
      sensitivity: 'base',
      numeric: true
    })
  })
  if (!searchQuery.value) return sorted
  const q = searchQuery.value.toLowerCase()
  return sorted.filter(
    (s) => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
  )
})

const filteredEnabledServers = computed(() =>
  filteredServers.value.filter((item) => !!item.enabled)
)
const filteredDisabledServers = computed(() =>
  filteredServers.value.filter((item) => !item.enabled)
)

const isStdioTransport = computed(
  () =>
    String(form.transport || '')
      .trim()
      .toLowerCase() === 'stdio'
)

// Tools computed properties
const filteredTools = computed(() => {
  if (!toolSearchText.value) return tools.value
  const search = toolSearchText.value.toLowerCase()
  return tools.value.filter(
    (t) =>
      t.name.toLowerCase().includes(search) ||
      (t.description && t.description.toLowerCase().includes(search))
  )
})

// Fetch MCP list
const fetchServers = async () => {
  try {
    loading.value = true
    error.value = null
    const result = await mcpApi.getMcpServers()
    if (result.success) {
      servers.value = result.data || []
      const defaultList = filteredEnabledServers.value.length
        ? filteredEnabledServers.value
        : filteredDisabledServers.value
      if (!currentServer.value && defaultList.length > 0) {
        selectServer(defaultList[0])
      } else if (currentServer.value) {
        const latest = servers.value.find((s) => s.name === currentServer.value.name)
        if (latest) {
          currentServer.value = latest
        }
      }
    } else {
      error.value = result.message || 'Failed to fetch MCP list'
    }
  } catch (err) {
    console.error('Failed to fetch MCP list:', err)
    error.value = err.message || 'Failed to fetch MCP list'
  } finally {
    loading.value = false
  }
}

// Fetch tools list
const fetchTools = async () => {
  if (!currentServer.value) return

  try {
    toolsLoading.value = true
    toolsError.value = null
    const result = await mcpApi.getMcpServerTools(currentServer.value.name)
    if (result.success) {
      tools.value = result.data || []
    } else {
      toolsError.value = result.message || 'Failed to fetch tools list'
      tools.value = []
    }
  } catch (err) {
    console.error('Failed to fetch tools list:', err)
    toolsError.value = err.message || 'Failed to fetch tools list'
    tools.value = []
  } finally {
    toolsLoading.value = false
  }
}

// Toggle tool status
const handleToggleTool = async (tool) => {
  if (!currentServer.value) return

  try {
    toggleToolLoading.value = tool.name
    const result = await mcpApi.toggleMcpServerTool(currentServer.value.name, tool.name)
    if (result.success) {
      message.success(result.message)
      const targetTool = tools.value.find((t) => t.name === tool.name)
      if (targetTool) {
        targetTool.enabled = result.enabled
      }
    } else {
      message.error(result.message || 'Operation failed')
    }
  } catch (err) {
    console.error('Failed to toggle tool status:', err)
    message.error(err.message || 'Operation failed')
  } finally {
    toggleToolLoading.value = null
  }
}

// Copy tool name
const copyToolName = async (name) => {
  try {
    await navigator.clipboard.writeText(name)
    message.success('Copied to clipboard')
  } catch {
    message.error('Copy failed')
  }
}

// Format timestamp
const formatTime = (timeStr) => formatFullDateTime(timeStr)

// Get transport color
const getTransportColor = (transport) => {
  const colors = {
    sse: 'orange',
    stdio: 'green',
    streamable_http: 'blue'
  }
  return colors[transport] || 'blue'
}

// Select MCP
const selectServer = (server) => {
  currentServer.value = server
  detailTab.value = 'general'
  fetchTools()
}

// Show Add modal
const showAddModal = () => {
  editMode.value = false
  formMode.value = 'form'
  Object.assign(form, {
    name: '',
    description: '',
    transport: 'streamable_http',
    url: '',
    command: '',
    args: [],
    env: null,
    headersText: '',
    timeout: null,
    sse_read_timeout: null,
    tags: [],
    icon: ''
  })
  jsonContent.value = ''
  formModalVisible.value = true
}

const applyServerToForm = (server) => {
  editMode.value = true
  formMode.value = 'form'
  Object.assign(form, {
    name: server.name,
    description: server.description || '',
    transport: server.transport,
    url: server.url || '',
    command: server.command || '',
    args: server.args || [],
    env: server.env || null,
    headersText: server.headers ? JSON.stringify(server.headers, null, 2) : '',
    timeout: server.timeout,
    sse_read_timeout: server.sse_read_timeout,
    tags: server.tags || [],
    icon: server.icon || ''
  })
  formModalVisible.value = true
}

// Show Edit modal
const showEditModal = async (server) => {
  try {
    const result = await mcpApi.getMcpServer(server.name)
    if (result.success && result.data) {
      applyServerToForm(result.data)
      return
    }
  } catch (err) {
    console.error('Failed to fetch MCP details, falling back to list data:', err)
  }
  applyServerToForm(server)
}

// Handle form submit
const handleFormSubmit = async () => {
  try {
    formLoading.value = true

    let data
    if (formMode.value === 'json') {
      try {
        data = JSON.parse(jsonContent.value)
      } catch {
        message.error('Invalid JSON format')
        return
      }
    } else {
      // Parse headers
      let headers = null
      if (form.headersText.trim()) {
        try {
          headers = JSON.parse(form.headersText)
        } catch {
          message.error('Request headers JSON format is invalid')
          return
        }
      }

      data = {
        name: form.name,
        description: form.description || null,
        transport: form.transport,
        url: form.url || null,
        command: form.command || null,
        args: form.args.length > 0 ? form.args : null,
        env: form.env,
        headers,
        timeout: form.timeout || null,
        sse_read_timeout: form.sse_read_timeout || null,
        tags: form.tags.length > 0 ? form.tags : null,
        icon: form.icon || null
      }
    }

    // Validate required fields
    if (!data.name?.trim()) {
      message.error('MCP name cannot be empty')
      return
    }
    if (!data.transport) {
      message.error('Please select a transport type')
      return
    }
    // Validate URL for HTTP/SSE transport
    if (['sse', 'streamable_http'].includes(data.transport)) {
      if (!data.url?.trim()) {
        message.error('MCP URL is required for HTTP/SSE transport')
        return
      }
    }
    // Validate command for StdIO transport
    if (data.transport === 'stdio') {
      if (!data.command?.trim()) {
        message.error('Command is required for StdIO transport')
        return
      }
    }

    if (editMode.value) {
      const result = await mcpApi.updateMcpServer(data.name, data)
      if (result.success) {
        message.success('MCP updated successfully')
      } else {
        message.error(result.message || 'Update failed')
        return
      }
    } else {
      const result = await mcpApi.createMcpServer(data)
      if (result.success) {
        message.success('MCP created successfully')
      } else {
        message.error(result.message || 'Creation failed')
        return
      }
    }

    formModalVisible.value = false
    await fetchServers()
  } catch (err) {
    console.error('Operation failed:', err)
    message.error(err.message || 'Operation failed')
  } finally {
    formLoading.value = false
  }
}

// Update MCP enabled status
const handleSetServerEnabled = async (server, enabled) => {
  try {
    toggleLoading.value = server.name
    const result = await mcpApi.updateMcpServerStatus(server.name, enabled)
    if (result.success) {
      message.success(result.message || `MCP ${enabled ? 'added' : 'removed'}`)
      await fetchServers()
      if (!enabled && currentServer.value?.name === server.name) {
        tools.value = []
      }
    } else {
      message.error(result.message || 'Operation failed')
    }
  } catch (err) {
    console.error('Failed to update status:', err)
    message.error(err.message || 'Operation failed')
  } finally {
    toggleLoading.value = null
  }
}

// Test MCP connection
const handleTestServer = async (server) => {
  try {
    testLoading.value = server.name
    const result = await mcpApi.testMcpServer(server.name)
    if (result.success) {
      message.success(result.message)
    } else {
      message.warning(result.message || 'Connection failed')
    }
  } catch (err) {
    console.error('MCP test failed:', err)
    message.error(err.message || 'Test failed')
  } finally {
    testLoading.value = null
  }
}

const handleDangerAction = async (server) => {
  if (server.enabled === false) {
    await handleSetServerEnabled(server, true)
    return
  }
  if (server.created_by === 'system') {
    await handleSetServerEnabled(server, false)
    return
  }
  confirmDeleteServer(server)
}

const handleInlineRemoveServer = async (server) => {
  if (server.created_by === 'system') {
    await handleSetServerEnabled(server, false)
    return
  }
  confirmDeleteServer(server)
}

const getServerActionLabel = (server) => {
  if (server?.enabled === false) {
    return 'Add'
  }
  return server?.created_by === 'system' ? 'Remove' : 'Delete'
}

const getServerActionTone = (server) => {
  return server?.enabled === false
    ? 'extension-panel-action-primary'
    : 'extension-panel-action-danger'
}

// Confirm deleting MCP
const confirmDeleteServer = (server) => {
  Modal.confirm({
    title: 'Confirm Delete MCP',
    content: `Are you sure you want to delete MCP "${server.name}"? This action cannot be undone.`,
    okText: 'Delete',
    okType: 'danger',
    cancelText: 'Cancel',
    async onOk() {
      try {
        const result = await mcpApi.deleteMcpServer(server.name)
        if (result.success) {
          message.success('MCP deleted successfully')
          await fetchServers()
        } else {
          message.error(result.message || 'Delete failed')
        }
      } catch (err) {
        console.error('Delete failed:', err)
        message.error(err.message || 'Delete failed')
      }
    }
  })
}

// Format JSON
const formatJson = () => {
  try {
    const obj = JSON.parse(jsonContent.value)
    jsonContent.value = JSON.stringify(obj, null, 2)
  } catch {
    message.error('Invalid JSON format; unable to format')
  }
}

// Parse JSON into form
const parseJsonToForm = () => {
  try {
    const obj = JSON.parse(jsonContent.value)
    Object.assign(form, {
      name: obj.name || '',
      description: obj.description || '',
      transport: obj.transport || 'streamable_http',
      url: obj.url || '',
      command: obj.command || '',
      args: obj.args || [],
      env: obj.env || null,
      headersText: obj.headers ? JSON.stringify(obj.headers, null, 2) : '',
      timeout: obj.timeout || null,
      sse_read_timeout: obj.sse_read_timeout || null,
      tags: obj.tags || [],
      icon: obj.icon || ''
    })
    formMode.value = 'form'
    message.success('Parsed into form')
  } catch {
    message.error('Invalid JSON format')
  }
}

// Initialize
onMounted(() => {
  fetchServers()
})

// Expose methods to the parent component
defineExpose({
  fetchServers,
  showAddModal
})
</script>

<style lang="less" scoped>
@import '@/assets/css/extensions.less';

.stats-section {
  padding: 8px 12px;
  .stats-text {
    font-size: 12px;
    color: var(--gray-500);
  }
}

.list-item {
  .server-icon {
    font-size: 18px;
  }
}

/* Tools list styles */
.tools-tab {
  .tools-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }

  .empty-tools {
    padding: 40px 0;
  }

  .tools-list {
    display: flex;
    flex-direction: column;
    gap: 12px;

    .tool-card {
      background: var(--gray-0);
      border: 1px solid var(--gray-150);
      border-radius: 8px;
      padding: 12px 16px;
      transition: all 0.2s ease;

      &:hover {
        border-color: var(--gray-200);
      }

      &.disabled {
        opacity: 0.6;
      }

      .tool-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;

        .tool-info {
          display: flex;
          align-items: center;
          gap: 8px;

          .tool-name {
            font-weight: 600;
            font-size: 14px;
            color: var(--gray-900);
          }

          .info-icon {
            color: var(--gray-400);
            cursor: pointer;
            &:hover {
              color: var(--gray-600);
            }
          }
        }

        .tool-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }
      }

      .tool-description {
        font-size: 13px;
        color: var(--gray-600);
        line-height: 1.4;
        margin-bottom: 8px;
      }

      :deep(.ant-collapse) {
        background: transparent;
        border: none;

        .ant-collapse-header {
          padding: 8px 0;
          font-size: 13px;
          color: var(--gray-600);
        }
        .ant-collapse-content-box {
          padding: 0;
        }
      }

      .params-list {
        display: flex;
        flex-direction: column;
        gap: 8px;

        .param-item {
          background: var(--gray-50);
          padding: 8px 12px;
          border-radius: 4px;

          .param-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;

            .param-name {
              font-weight: 500;
              font-size: 13px;
              color: var(--gray-900);
              font-family: @mono-font;
            }
            .param-required {
              font-size: 11px;
              color: var(--color-error-500);
              background: var(--color-error-50);
              padding: 1px 6px;
              border-radius: 3px;
            }
            .param-type {
              font-size: 11px;
              color: var(--gray-500);
              background: var(--gray-100);
              padding: 1px 6px;
              border-radius: 3px;
              font-family: @mono-font;
            }
          }

          .param-desc {
            font-size: 12px;
            color: var(--gray-600);
            line-height: 1.4;
          }
        }
      }
    }
  }
}

/* Modal styles */
.server-modal {
  .mode-switch {
    margin-bottom: 16px;
    text-align: right;
  }
  .json-mode {
    .json-textarea {
      font-family: @mono-font;
      font-size: 13px;
    }
    .json-actions {
      margin-top: 12px;
      display: flex;
      gap: 8px;
    }
  }
}
</style>
