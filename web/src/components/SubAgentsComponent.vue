<template>
  <div class="subagents-component extension-page-root">
    <div v-if="loading" class="loading-bar-wrapper">
      <div class="loading-bar"></div>
    </div>
    <div class="layout-wrapper" :class="{ 'content-loading': loading }">
      <!-- Left: subagent list -->
      <div class="sidebar-list">
        <!-- Search box -->
        <div class="sidebar-toolbar">
          <div class="search-box">
            <a-input
              v-model:value="searchQuery"
              placeholder="Search Subagents..."
              allow-clear
              class="search-input"
            >
              <template #prefix><Search :size="14" class="text-muted" /></template>
            </a-input>
          </div>

          <a-tooltip title="Refresh Subagents">
            <a-button class="sidebar-tool" :disabled="loading" @click="fetchSubAgents">
              <RotateCw :size="14" />
            </a-button>
          </a-tooltip>
        </div>

        <!-- Subagent list -->
        <div class="list-container">
          <div
            v-if="!filteredEnabledSubAgents.length && !filteredDisabledSubAgents.length"
            class="empty-text"
          >
            <a-empty
              :image="false"
              :description="searchQuery ? 'No matching subagents' : 'No subagents yet'"
            />
          </div>
          <div v-if="filteredEnabledSubAgents.length" class="list-section-title">Added</div>
          <template
            v-for="(agent, index) in filteredEnabledSubAgents"
            :key="`enabled-${agent.name}`"
          >
            <div
              class="list-item extension-list-item"
              :class="{ active: currentAgent?.name === agent.name }"
              @click="selectAgent(agent)"
            >
              <div class="item-main-row">
                <div class="item-header">
                  <Bot :size="16" class="item-icon" />
                  <span class="item-name">{{ agent.name }}</span>
                </div>
                <div class="item-status">
                  <span class="status-chip status-chip-success">Added</span>
                  <button
                    type="button"
                    class="inline-hover-action danger"
                    @click.stop="handleSetAgentEnabled(agent, false)"
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div class="item-details">
                <span class="item-desc">{{ agent.description || 'No description available' }}</span>
                <div class="item-tags">
                  <span v-if="agent.is_builtin" class="source-tag builtin">Built-in</span>
                </div>
              </div>
            </div>
            <div
              v-if="
                index < filteredEnabledSubAgents.length - 1 || filteredDisabledSubAgents.length > 0
              "
              class="list-separator"
            ></div>
          </template>

          <div v-if="filteredDisabledSubAgents.length" class="list-section-title">Available</div>
          <template
            v-for="(agent, index) in filteredDisabledSubAgents"
            :key="`disabled-${agent.name}`"
          >
            <div
              class="list-item extension-list-item"
              :class="{ active: currentAgent?.name === agent.name }"
              @click="selectAgent(agent)"
            >
              <div class="item-main-row">
                <div class="item-header">
                  <Bot :size="16" class="item-icon" />
                  <span class="item-name">{{ agent.name }}</span>
                </div>
                <div class="item-status">
                  <button
                    type="button"
                    class="skill-inline-action skill-inline-action-primary"
                    @click.stop="handleSetAgentEnabled(agent, true)"
                  >
                    Add
                  </button>
                </div>
              </div>
              <div class="item-details">
                <span class="item-desc">{{ agent.description || 'No description available' }}</span>
                <div class="item-tags">
                  <span v-if="agent.is_builtin" class="source-tag builtin">Built-in</span>
                </div>
              </div>
            </div>
            <div v-if="index < filteredDisabledSubAgents.length - 1" class="list-separator"></div>
          </template>
        </div>
      </div>

      <!-- Right: detail panel -->
      <div class="main-panel">
        <Transition name="fade-slide" mode="out-in">
          <div v-if="!currentAgent" :key="'empty'" class="unselected-state">
            <div class="hint-box-premium">
              <div class="icon-orb">
                <Bot :size="64" />
              </div>
              <h3>Subagents Lab</h3>
              <p>Explore and configure your specialized assistant plugins</p>
              <div class="hint-shortcuts">
                <div class="shortcut-item">
                  <div class="dot"></div>
                  <span>Select a plugin from the left panel to view details</span>
                </div>
                <div class="shortcut-item">
                  <div class="dot"></div>
                  <span>Manage built-in or custom subagents</span>
                </div>
              </div>
            </div>
          </div>

          <div v-else :key="currentAgent.name" class="panel-content-wrapper">
            <div class="panel-header-premium">
              <div class="header-mesh-container">
                <div class="mesh-layer"></div>
              </div>
              <div class="panel-top-bar">
                <h2 class="panel-title-row">
                  <div class="title-icon-wrapper">
                    <Bot :size="20" class="panel-title-icon" />
                  </div>
                  <div class="title-text-group">
                    <span class="agent-name-main">{{ currentAgent.name }}</span>
                    <div class="agent-metadata">
                      <span class="meta-tag">{{
                        currentAgent.is_builtin ? 'Built-in system' : 'Custom'
                      }}</span>
                      <span v-if="currentAgent.model" class="meta-tag">
                        <Cpu :size="10" />
                        {{
                          typeof currentAgent.model === 'string' ? currentAgent.model : 'Model spec'
                        }}
                      </span>
                    </div>
                  </div>
                </h2>
                <div class="panel-actions">
                  <a-space :size="8">
                    <a-button
                      size="middle"
                      @click="showEditModal(currentAgent)"
                      class="premium-action-btn"
                      v-if="!currentAgent.is_builtin"
                    >
                      <template #icon><Pencil :size="14" /></template>
                      <span>Edit</span>
                    </a-button>
                    <a-button
                      size="middle"
                      danger
                      ghost
                      :disabled="currentAgent.is_builtin"
                      @click="confirmDeleteAgent(currentAgent)"
                      class="premium-action-btn danger"
                      v-if="!currentAgent.is_builtin"
                    >
                      <template #icon><Trash2 :size="14" /></template>
                      <span>Delete</span>
                    </a-button>
                  </a-space>
                </div>
              </div>
            </div>

            <div class="detail-section-container">
              <div class="detail-section">
                <div class="section-header">
                  <MessageSquare :size="14" />
                  <span>System Prompt</span>
                </div>
                <div class="section-content">
                  <div class="code-panel">
                    <pre class="code-panel-pre">{{ currentAgent.system_prompt }}</pre>
                  </div>
                </div>
              </div>

              <div class="detail-section" v-if="currentAgent.description">
                <div class="section-header">
                  <FileText :size="14" />
                  <span>Description</span>
                </div>
                <div class="section-content description">
                  {{ currentAgent.description }}
                </div>
              </div>

              <div class="detail-section" v-if="currentAgent.model">
                <div class="section-header">
                  <Cpu :size="14" />
                  <span>Model Override</span>
                </div>
                <div class="section-content">
                  {{ currentAgent.model }}
                </div>
              </div>

              <div
                class="detail-section"
                v-if="currentAgent.tools && currentAgent.tools.length > 0"
              >
                <div class="section-header">
                  <Wrench :size="14" />
                  <span>Tools</span>
                </div>
                <div class="section-content">
                  <a-tag v-for="tool in currentAgent.tools" :key="tool">{{ tool }}</a-tag>
                </div>
              </div>

              <div
                class="detail-section"
                v-if="currentAgent.is_builtin || currentAgent.enabled === false"
              >
                <div class="section-header">
                  <Info :size="14" />
                  <span>Type</span>
                </div>
                <div class="section-content">
                  <a-tag v-if="currentAgent.is_builtin" color="blue">Built-in</a-tag>
                  <a-tag v-else color="default">Custom</a-tag>
                  <a-tag v-if="currentAgent.enabled === false" color="default">Not added</a-tag>
                </div>
              </div>

              <div class="detail-section">
                <div class="section-header">
                  <Clock :size="14" />
                  <span>Metadata</span>
                </div>
                <div class="section-content meta-info">
                  <div class="meta-item">
                    <span class="meta-label">Created At</span>
                    <span class="meta-value">{{ formatTime(currentAgent.created_at) }}</span>
                  </div>
                  <div class="meta-item">
                    <span class="meta-label">Updated At</span>
                    <span class="meta-value">{{ formatTime(currentAgent.updated_at) }}</span>
                  </div>
                  <div class="meta-item" v-if="currentAgent.created_by">
                    <span class="meta-label">Created By</span>
                    <span class="meta-value">{{ currentAgent.created_by }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </div>

    <!-- Add/Edit Subagent modal -->
    <a-modal
      v-model:open="formModalVisible"
      :title="editMode ? 'Edit Subagent' : 'Add Subagent'"
      @ok="handleFormSubmit"
      :confirmLoading="formLoading"
      @cancel="formModalVisible = false"
      :maskClosable="false"
      width="600px"
    >
      <a-form layout="vertical" class="extension-form">
        <a-form-item label="Name" required class="form-item">
          <a-input
            v-model:value="form.name"
            placeholder="Enter Subagent name (unique identifier)"
            :disabled="editMode"
          />
        </a-form-item>

        <a-form-item label="Description" class="form-item">
          <a-input v-model:value="form.description" placeholder="Enter subagent description" />
        </a-form-item>

        <a-form-item label="System Prompt" required class="form-item">
          <a-textarea
            v-model:value="form.system_prompt"
            placeholder="Enter system prompt"
            :rows="6"
          />
        </a-form-item>

        <a-form-item label="Tools" class="form-item">
          <a-select
            v-model:value="form.tools"
            mode="tags"
            placeholder="Select or enter tool names"
            style="width: 100%"
            :options="availableTools"
            @focus="fetchAvailableTools"
          />
        </a-form-item>

        <a-form-item label="Model Override (optional)" class="form-item">
          <div class="model-override-row">
            <ModelSelectorComponent
              :model_spec="form.model"
              placeholder="Select a model"
              class="model-selector-full"
              @select-model="handleModelSelect"
            />
            <a-button v-if="form.model" type="link" size="small" @click="form.model = ''">
              Clear
            </a-button>
          </div>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  Search,
  Bot,
  Pencil,
  Trash2,
  RotateCw,
  Info,
  MessageSquare,
  FileText,
  Cpu,
  Wrench,
  Clock
} from 'lucide-vue-next'
import { subagentApi } from '@/apis/subagent_api'
import { toolApi } from '@/apis/tool_api'
import { formatFullDateTime } from '@/utils/time'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'

// State
const loading = ref(false)
const error = ref(null)
const subagents = ref([])
const searchQuery = ref('')
const currentAgent = ref(null)
const availableTools = ref([])

// Form state
const formModalVisible = ref(false)
const formLoading = ref(false)
const editMode = ref(false)
const form = reactive({
  name: '',
  description: '',
  system_prompt: '',
  tools: [],
  model: ''
})

const getSortedSubAgents = (items) => {
  return [...items].sort((a, b) => {
    // Sort built-in agents first
    if (a.is_builtin !== b.is_builtin) {
      return a.is_builtin ? -1 : 1
    }
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  })
}

// Computed properties
const filteredSubAgents = computed(() => {
  const sorted = getSortedSubAgents(subagents.value)
  if (!searchQuery.value) return sorted
  const q = searchQuery.value.toLowerCase()
  return sorted.filter(
    (a) => a.name.toLowerCase().includes(q) || (a.description || '').toLowerCase().includes(q)
  )
})

const filteredEnabledSubAgents = computed(() =>
  filteredSubAgents.value.filter((item) => item.enabled !== false)
)
const filteredDisabledSubAgents = computed(() =>
  filteredSubAgents.value.filter((item) => item.enabled === false)
)

// Fetch subagent list
const fetchSubAgents = async () => {
  try {
    loading.value = true
    error.value = null
    const result = await subagentApi.getSubAgents()
    if (result.success) {
      subagents.value = result.data || []
      // Preserve selection
      if (currentAgent.value) {
        const latest = subagents.value.find((a) => a.name === currentAgent.value.name)
        if (latest) {
          currentAgent.value = latest
        } else {
          currentAgent.value = null
        }
      }
      // Select the first added item by default
      const defaultList = filteredEnabledSubAgents.value.length
        ? filteredEnabledSubAgents.value
        : filteredDisabledSubAgents.value
      if (!currentAgent.value && defaultList.length > 0) {
        currentAgent.value = defaultList[0]
      }
    } else {
      error.value = result.message || 'Failed to fetch list'
    }
  } catch (err) {
    console.error('Failed to fetch subagent list:', err)
    error.value = err.message || 'Failed to fetch list'
  } finally {
    loading.value = false
  }
}

// Fetch available tool list
const fetchAvailableTools = async () => {
  if (availableTools.value.length > 0) return
  try {
    const result = await toolApi.getToolOptions()
    if (result.success && result.data) {
      availableTools.value = result.data
    }
  } catch (err) {
    console.error('Failed to fetch tool options:', err)
  }
}

// Format timestamp
const formatTime = (timeStr) => formatFullDateTime(timeStr)

const handleModelSelect = (spec) => {
  form.model = spec || ''
}

const handleSetAgentEnabled = async (agent, enabled) => {
  try {
    const result = await subagentApi.updateSubAgentStatus(agent.name, enabled)
    if (result.success) {
      message.success(result.message || `Subagent has been ${enabled ? 'added' : 'removed'}`)
      await fetchSubAgents()
    } else {
      message.error(result.message || 'Operation failed')
    }
  } catch (err) {
    console.error('Failed to update status:', err)
    message.error(err.message || 'Operation failed')
  }
}

// Select subagent
const selectAgent = (agent) => {
  currentAgent.value = agent
}

// Show Add modal
const showAddModal = () => {
  editMode.value = false
  Object.assign(form, {
    name: '',
    description: '',
    system_prompt: '',
    tools: [],
    model: ''
  })
  formModalVisible.value = true
}

// Show Edit modal
const showEditModal = async (agent) => {
  try {
    const result = await subagentApi.getSubAgent(agent.name)
    if (result.success && result.data) {
      editMode.value = true
      Object.assign(form, {
        name: result.data.name,
        description: result.data.description || '',
        system_prompt: result.data.system_prompt || '',
        tools: result.data.tools || [],
        model: result.data.model || ''
      })
      formModalVisible.value = true
      return
    }
  } catch (err) {
    console.error('Failed to fetch subagent detail, fallback to list data:', err)
  }
  // Fallback: use list data
  editMode.value = true
  Object.assign(form, {
    name: agent.name,
    description: agent.description || '',
    system_prompt: agent.system_prompt || '',
    tools: agent.tools || [],
    model: agent.model || ''
  })
  formModalVisible.value = true
}

// Handle form submit
const handleFormSubmit = async () => {
  try {
    // Validation
    if (!form.name?.trim()) {
      message.error('Name cannot be empty')
      return
    }
    if (!form.system_prompt?.trim()) {
      message.error('System prompt cannot be empty')
      return
    }

    formLoading.value = true

    const data = {
      name: form.name.trim(),
      description: form.description || '',
      system_prompt: form.system_prompt,
      tools: form.tools || [],
      model: form.model || null
    }

    if (editMode.value) {
      const result = await subagentApi.updateSubAgent(form.name, data)
      if (result.success) {
        message.success('Subagent updated successfully')
      } else {
        message.error(result.message || 'Update failed')
        return
      }
    } else {
      const result = await subagentApi.createSubAgent(data)
      if (result.success) {
        message.success('Subagent created successfully')
      } else {
        message.error(result.message || 'Creation failed')
        return
      }
    }

    formModalVisible.value = false
    await fetchSubAgents()
  } catch (err) {
    console.error('Operation failed:', err)
    message.error(err.message || 'Operation failed')
  } finally {
    formLoading.value = false
  }
}

// Confirm deleting subagent
const confirmDeleteAgent = (agent) => {
  Modal.confirm({
    title: 'Confirm Delete Subagent',
    content: `Are you sure you want to delete subagent "${agent.name}"? This action cannot be undone.`,
    okText: 'Delete',
    okType: 'danger',
    cancelText: 'Cancel',
    async onOk() {
      try {
        const result = await subagentApi.deleteSubAgent(agent.name)
        if (result.success) {
          message.success('Subagent deleted successfully')
          if (currentAgent.value?.name === agent.name) {
            currentAgent.value = null
          }
          await fetchSubAgents()
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

// Initialize
onMounted(() => {
  fetchSubAgents()
})

// Expose methods to the parent component
defineExpose({
  fetchSubAgents,
  showAddModal
})
</script>

<style lang="less" scoped>
@import '@/assets/css/extensions.less';

.panel-header-premium {
  position: relative;
  overflow: hidden;
  border-bottom: 1px solid var(--gray-150);
  background: var(--main-0);

  .header-mesh-container {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 120px;
    z-index: 0;
    opacity: 0.6;
    pointer-events: none;

    .mesh-layer {
      width: 100%;
      height: 100%;
      background: var(--mesh-grad-1), var(--mesh-grad-2);
      filter: blur(40px);
    }
  }

  .panel-top-bar {
    position: relative;
    z-index: 1;
    padding: 24px 24px 20px 24px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 1) 100%);
  }
}

.title-icon-wrapper {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--main-50);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--main-600);
  box-shadow: var(--shadow-1);
}

.title-text-group {
  display: flex;
  flex-direction: column;
  gap: 2px;

  .agent-name-main {
    font-size: 20px;
    font-weight: 700;
    color: var(--gray-1000);
    letter-spacing: -0.5px;
  }

  .agent-metadata {
    display: flex;
    gap: 8px;
    align-items: center;

    .meta-tag {
      font-size: 11px;
      color: var(--gray-500);
      background: var(--gray-50);
      padding: 1px 8px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      gap: 4px;
    }
  }
}

.premium-action-btn {
  border-radius: 8px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: var(--transition-smooth);

  &:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-2);
  }

  &.danger:hover {
    border-color: var(--color-error-500);
    color: var(--color-error-500);
  }
}

.detail-section-container {
  padding: 24px;
}

.detail-section {
  background: var(--main-1);
  border: 1px solid var(--gray-100);
  border-radius: var(--radius-lg);
  padding: 20px;
  margin-bottom: 24px !important;
  transition: var(--transition-smooth);

  &:hover {
    border-color: var(--main-200);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
  }

  .section-header {
    margin-bottom: 12px !important;
    font-size: 14px !important;
    color: var(--gray-800) !important;

    svg {
      color: var(--main-500) !important;
    }
  }
}

.code-panel {
  background: #fdfdfd;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  padding: 16px;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.02);
}

.hint-box-premium {
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 400px;
  animation: float 6s ease-in-out infinite;

  .icon-orb {
    width: 120px;
    height: 120px;
    background: var(--main-50);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--main-500);
    margin-bottom: 24px;
    box-shadow: 0 10px 30px rgba(57, 150, 174, 0.15);
    position: relative;

    &::after {
      content: '';
      position: absolute;
      inset: -5px;
      border: 2px dashed var(--main-200);
      border-radius: 50%;
      animation: rotate-slow 20s linear infinite;
    }
  }

  h3 {
    font-size: 24px;
    font-weight: 700;
    color: var(--gray-900);
    margin-bottom: 8px;
  }

  p {
    color: var(--gray-500);
    margin-bottom: 32px;
  }

  .hint-shortcuts {
    display: flex;
    flex-direction: column;
    gap: 12px;
    width: 100%;

    .shortcut-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 20px;
      background: var(--main-0);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-1);
      font-size: 13px;
      color: var(--gray-700);
      border: 1px solid var(--gray-100);

      .dot {
        width: 6px;
        height: 6px;
        background: var(--main-400);
        border-radius: 50%;
      }
    }
  }
}

@keyframes float {
  0% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-10px);
  }
  100% {
    transform: translateY(0px);
  }
}

@keyframes rotate-slow {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}

.panel-content-wrapper {
  height: 100%;
}
</style>
