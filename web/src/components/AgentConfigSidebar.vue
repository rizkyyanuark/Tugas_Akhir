<template>
  <div class="agent-config-sidebar" :class="{ open: isOpen }">
    <!-- Sidebar header -->
    <div class="sidebar-header">
      <div class="header-top-row">
        <div v-if="selectedAgentId" class="config-manage-row">
          <a-select
            :value="selectedAgentConfigId"
            :options="configSwitchOptions"
            class="config-switch-select"
            placeholder="Select configuration"
            @update:value="handleConfigSwitch"
          />
        </div>
        <div class="header-actions">
          <a-tooltip
            v-if="!isEmptyConfig && userStore.isAdmin"
            :title="isCurrentDefault ? 'Currently the default config' : 'Set as default config'"
          >
            <a-button
              type="text"
              shape="circle"
              class="icon-btn lucide-icon-btn"
              :class="{ 'is-default': isCurrentDefault }"
              @click="setAsDefault"
            >
              <Star :size="18" :fill="isCurrentDefault ? 'currentColor' : 'none'" />
            </a-button>
          </a-tooltip>

          <a-tooltip v-if="!isEmptyConfig && userStore.isAdmin" title="Delete config">
            <a-button
              type="text"
              shape="circle"
              danger
              class="icon-btn lucide-icon-btn"
              @click="confirmDeleteConfig"
              :disabled="isDeletingConfig"
            >
              <Trash2 :size="18" />
            </a-button>
          </a-tooltip>

          <a-button type="text" size="small" @click="closeSidebar" class="icon-btn lucide-icon-btn">
            <X :size="16" />
          </a-button>
        </div>
      </div>
    </div>

    <!-- Sidebar content -->
    <div class="sidebar-content">
      <div class="agent-info" v-if="selectedAgent">
        <!-- <div class="agent-basic-info">
          <p class="agent-description">{{ selectedAgent.description }}</p>
        </div> -->

        <!-- <a-divider /> -->

        <div class="config-segment" v-if="!isEmptyConfig">
          <a-segmented v-model:value="currentSegment" :options="segmentOptions" block />
        </div>

        <div
          v-if="selectedAgentId && configurableItems"
          class="config-form-content"
          :class="{ 'is-readonly': isReadOnlyConfig }"
        >
          <!-- Config form -->
          <a-form :model="agentConfig" layout="vertical" class="config-form">
            <a-alert
              v-if="isEmptyConfig"
              type="warning"
              message="This agent has no configuration items"
              show-icon
              class="config-alert"
            />
            <!-- Display all configuration items uniformly -->
            <template v-for="(value, key) in filteredConfigurableItems" :key="key">
              <a-form-item
                v-if="shouldShowConfig(key, value)"
                :label="getConfigLabel(key, value)"
                :name="key"
                class="config-item"
              >
                <p v-if="value.description" class="config-description">{{ value.description }}</p>

                <!-- <div>{{ value }}</div> -->
                <!-- Model selection -->
                <div
                  v-if="value.template_metadata.kind === 'llm'"
                  class="model-selector"
                  :class="{ 'is-readonly': isReadOnlyConfig }"
                >
                  <ModelSelectorComponent
                    @select-model="(spec) => handleModelChange(key, spec)"
                    :model_spec="agentConfig[key] || ''"
                  />
                </div>

                <!-- System prompt -->
                <div
                  v-else-if="value.template_metadata.kind === 'prompt'"
                  class="system-prompt-container"
                >
                  <div class="system-prompt-display" @click="openSystemPromptModal(key)">
                    <div
                      class="system-prompt-content"
                      :class="{ 'is-placeholder': !agentConfig[key] }"
                    >
                      {{ agentConfig[key] || getPlaceholder(key, value) }}
                    </div>
                    <div class="edit-hint">
                      {{ isReadOnlyConfig ? 'View' : 'Click to view and edit' }}
                    </div>
                  </div>
                </div>

                <!-- Boolean type -->
                <a-switch
                  v-else-if="typeof agentConfig[key] === 'boolean'"
                  :checked="agentConfig[key]"
                  :disabled="isReadOnlyConfig"
                  @update:checked="(val) => updateConfigValue(key, val)"
                />

                <!-- Single select -->
                <a-select
                  v-else-if="
                    value?.options.length > 0 && (value?.type === 'str' || value?.type === 'select')
                  "
                  :value="agentConfig[key]"
                  :disabled="isReadOnlyConfig"
                  @update:value="(val) => updateConfigValue(key, val)"
                  class="config-select"
                >
                  <a-select-option v-for="option in value.options" :key="option" :value="option">
                    {{ option.label || option }}
                  </a-select-option>
                </a-select>

                <!-- Multi-select / tool list (handled uniformly) -->
                <div v-else-if="isListConfig(key, value)" class="list-config-container">
                  <!-- Case 1: <= 5 options, inline list -->
                  <div v-if="getConfigOptions(value).length <= 5" class="multi-select-cards">
                    <div class="multi-select-label">
                      <span
                        >Selected {{ getSelectedCount(key) }} items | Total
                        {{ getConfigOptions(value).length }} items</span
                      >
                      <div v-if="!isReadOnlyConfig" class="label-actions">
                        <a-button
                          type="link"
                          size="small"
                          class="clear-btn"
                          @click="clearSelection(key)"
                          v-if="getSelectedCount(key) > 0"
                        >
                          Clear
                        </a-button>
                        <template v-if="isToolsKind(value.template_metadata?.kind)">
                          <a-divider type="vertical" />
                          <a-button
                            type="link"
                            size="small"
                            @click="refreshConfigOptions(key, value.template_metadata.kind)"
                            class="inline-action-btn lucide-icon-btn"
                          >
                            <RotateCw :size="12" />
                            Refresh
                          </a-button>
                          <a-button
                            type="link"
                            size="small"
                            @click="navigateToConfigPage(value.template_metadata.kind)"
                            class="inline-action-btn lucide-icon-btn"
                          >
                            <Settings :size="12" />
                            Configure
                          </a-button>
                        </template>
                      </div>
                    </div>

                    <div class="options-grid">
                      <div
                        v-for="option in isReadOnlyConfig
                          ? getConfigOptions(value).filter((opt) =>
                              isOptionSelected(key, getOptionValue(opt))
                            )
                          : getConfigOptions(value)"
                        :key="getOptionValue(option)"
                        class="option-card"
                        :class="{
                          selected: isOptionSelected(key, getOptionValue(option)),
                          unselected: !isOptionSelected(key, getOptionValue(option)),
                          readonly: isReadOnlyConfig
                        }"
                        @click="!isReadOnlyConfig && toggleOption(key, getOptionValue(option))"
                      >
                        <div class="option-content">
                          <span class="option-text">{{ getOptionLabel(option) }}</span>
                          <div class="option-indicator">
                            <Check
                              v-if="isOptionSelected(key, getOptionValue(option))"
                              :size="16"
                            />
                            <Plus v-else :size="16" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- Case 2: > 5 options, modal trigger -->

                  <div v-else class="selection-container">
                    <div class="selection-summary">
                      <div class="selection-summary-info">
                        <span class="selection-count"
                          >Selected {{ getSelectedCount(key) }} items | Total
                          {{ getConfigOptions(value).length }} items</span
                        >

                        <a-button
                          v-if="!isReadOnlyConfig && getSelectedCount(key) > 0"
                          type="link"
                          size="small"
                          class="clear-btn"
                          @click="clearSelection(key)"
                        >
                          Clear
                        </a-button>
                      </div>

                      <a-button
                        v-if="!isReadOnlyConfig"
                        type="primary"
                        size="small"
                        class="selection-trigger-btn"
                        @click="openSelectionModal(key)"
                      >
                        Select...
                      </a-button>
                    </div>

                    <!-- Selected preview tags -->

                    <div v-if="getSelectedCount(key) > 0" class="selection-preview">
                      <a-tag
                        v-for="val in agentConfig[key]"
                        :key="val"
                        :closable="!isReadOnlyConfig"
                        @close="toggleOption(key, val)"
                        class="selection-tag"
                      >
                        {{ getOptionLabelFromValue(key, val) }}
                      </a-tag>
                    </div>
                  </div>
                </div>

                <!-- Number -->
                <a-input-number
                  v-else-if="
                    value?.type === 'number' || value?.type === 'int' || value?.type === 'float'
                  "
                  :value="agentConfig[key]"
                  :disabled="isReadOnlyConfig"
                  @update:value="(val) => updateConfigValue(key, val)"
                  :placeholder="getPlaceholder(key, value)"
                  class="config-input-number"
                />

                <!-- Slider -->
                <a-slider
                  v-else-if="value?.type === 'slider'"
                  :value="agentConfig[key]"
                  :disabled="isReadOnlyConfig"
                  @update:value="(val) => updateConfigValue(key, val)"
                  :min="value.min"
                  :max="value.max"
                  :step="value.step"
                  class="config-slider"
                />

                <!-- Other types -->
                <a-input
                  v-else
                  :value="agentConfig[key]"
                  :disabled="isReadOnlyConfig"
                  @update:value="(val) => updateConfigValue(key, val)"
                  :placeholder="getPlaceholder(key, value)"
                  class="config-input"
                />
              </a-form-item>
            </template>
          </a-form>
        </div>
      </div>
    </div>

    <!-- Fixed footer actions -->
    <div class="sidebar-footer" v-if="userStore.isAdmin && selectedAgentId">
      <div class="form-actions">
        <a-button
          type="primary"
          @click="saveConfig"
          class="footer-main-btn save-btn"
          :class="{ changed: agentStore.hasConfigChanges }"
          :disabled="isSavingConfig || isEmptyConfig"
        >
          Save
        </a-button>
      </div>
    </div>

    <!-- Generic selection modal -->

    <a-modal
      v-model:open="createConfigModalOpen"
      title="Create config"
      :width="360"
      :confirmLoading="createConfigLoading"
      @ok="handleCreateConfig"
      @cancel="closeCreateConfigModal"
    >
      <a-input v-model:value="createConfigName" placeholder="Enter config name" allow-clear />
    </a-modal>

    <a-modal
      v-model:open="selectionModalOpen"
      :title="`Select ${configurableItems[currentConfigKey]?.name || 'item'}`"
      :width="800"
      :footer="null"
      :maskClosable="false"
      class="selection-modal"
    >
      <div class="selection-modal-content">
        <div class="selection-search">
          <a-input
            v-model:value="selectionSearchText"
            placeholder="Search..."
            allow-clear
            class="search-input"
          >
            <template #prefix>
              <Search :size="16" class="search-icon" />
            </template>
          </a-input>
          <template v-if="!isReadOnlyConfig && isToolsKind(currentConfigKind)">
            <a-button
              type="text"
              size="small"
              @click="refreshConfigOptions(currentConfigKey, currentConfigKind)"
              class="inline-action-btn lucide-icon-btn"
              title="Refresh list"
            >
              <RotateCw :size="14" />
              Refresh
            </a-button>
            <a-button
              type="text"
              size="small"
              @click="navigateToConfigPage(currentConfigKind)"
              class="inline-action-btn lucide-icon-btn"
              title="Go to config page"
            >
              <Settings :size="14" />
              Configure
            </a-button>
          </template>
        </div>

        <div class="selection-list">
          <div
            v-for="option in filteredOptions"
            :key="getOptionValue(option)"
            class="selection-item"
            :class="{ selected: tempSelectedValues.includes(getOptionValue(option)) }"
            @click="!isReadOnlyConfig && toggleModalSelection(getOptionValue(option))"
          >
            <div class="selection-item-content">
              <div class="selection-item-header">
                <span class="selection-item-name">{{ getOptionLabel(option) }}</span>

                <div class="selection-item-indicator">
                  <Check v-if="tempSelectedValues.includes(getOptionValue(option))" :size="16" />

                  <Plus v-else :size="16" />
                </div>
              </div>

              <div v-if="getOptionDescription(option)" class="selection-item-description">
                {{ getOptionDescription(option) }}
              </div>
            </div>
          </div>
        </div>

        <div class="selection-modal-footer">
          <div class="selected-count">Selected {{ tempSelectedValues.length }} items</div>

          <div class="modal-actions">
            <a-button @click="closeSelectionModal">Cancel</a-button>

            <a-button v-if="!isReadOnlyConfig" type="primary" @click="confirmSelection">
              Confirm
            </a-button>
          </div>
        </div>
      </div>
    </a-modal>

    <a-modal
      v-model:open="systemPromptModalOpen"
      :title="systemPromptModalTitle"
      :width="620"
      :maskClosable="false"
      @cancel="closeSystemPromptModal"
      class="system-prompt-modal"
    >
      <div class="system-prompt-modal-content">
        <a-textarea
          v-model:value="systemPromptDraft"
          :rows="14"
          :disabled="isReadOnlyConfig"
          :placeholder="systemPromptModalPlaceholder"
          class="system-prompt-modal-input"
        />
      </div>

      <template #footer>
        <a-button @click="closeSystemPromptModal">{{
          isReadOnlyConfig ? 'Close' : 'Cancel'
        }}</a-button>
        <a-button v-if="!isReadOnlyConfig" type="primary" @click="saveSystemPrompt">
          Save
        </a-button>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import { X, Trash2, Check, Plus, Search, Star, RotateCw, Settings } from 'lucide-vue-next'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { useAgentStore } from '@/stores/agent'
import { useUserStore } from '@/stores/user'
import { useDatabaseStore } from '@/stores/database'
import { mcpApi } from '@/apis/mcp_api'
import { skillApi } from '@/apis/skill_api'
import { subagentApi } from '@/apis/subagent_api'
import { toolApi } from '@/apis/tool_api'
import { storeToRefs } from 'pinia'

// Props
const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  }
})

// Emits
const emit = defineEmits(['close'])

// Store management
const agentStore = useAgentStore()
const userStore = useUserStore()
const databaseStore = useDatabaseStore()
const router = useRouter()

watch(
  () => props.isOpen,
  async (val) => {
    if (val) {
      // Force refresh to fetch the latest data
      databaseStore.loadDatabases(true).catch(() => {})
      loadLiveSkillOptions(true).catch(() => {})
      loadMcpOptions(true).catch(() => {})
      loadSubagentOptions(true).catch(() => {})
      loadToolOptions(true).catch(() => {})
      if (selectedAgentId.value) {
        agentStore.fetchAgentConfigs(selectedAgentId.value).catch((error) => {
          console.error('Failed to refresh agent config list:', error)
        })
        try {
          await agentStore.fetchAgentDetail(selectedAgentId.value, true)
        } catch (error) {
          console.error('Failed to refresh agent config items:', error)
        }
      }
    }
  }
)

const {
  selectedAgent,
  selectedAgentId,
  selectedAgentConfigId,
  selectedConfigSummary,
  agentConfigs,
  agentConfig,
  configurableItems
} = storeToRefs(agentStore)

// console.log(availableTools.value)

// Local state
const selectionModalOpen = ref(false)
const currentConfigKey = ref(null)
const tempSelectedValues = ref([])
const selectionSearchText = ref('')
const systemPromptModalOpen = ref(false)
const currentSystemPromptKey = ref(null)
const systemPromptDraft = ref('')
const liveSkillOptions = ref([])
const liveMcpOptions = ref([])
const liveSubagentOptions = ref([])
const toolOptionsFromApi = ref([])
const createConfigModalOpen = ref(false)
const createConfigLoading = ref(false)
const createConfigName = ref('')
const CREATE_CONFIG_OPTION_VALUE = '__create_config__'
const currentSegment = ref('model')
const segmentOptions = [
  { label: 'Model', value: 'model' },
  { label: 'Tools', value: 'tools' },
  { label: 'Other', value: 'other' }
]

const isEmptyConfig = computed(() => {
  return !selectedAgentId.value || Object.keys(configurableItems.value).length === 0
})

const isCurrentDefault = computed(() => {
  return !!selectedConfigSummary.value?.is_default
})

const isReadOnlyConfig = computed(() => !userStore.isAdmin)

const isSavingConfig = ref(false)
const isDeletingConfig = ref(false)

const segmentConfigKeys = computed(() => {
  const keys = Object.keys(configurableItems.value)
  return {
    model: keys.filter((key) => {
      const meta = configurableItems.value[key]?.template_metadata?.kind
      return meta === 'llm' || meta === 'prompt'
    }),
    tools: keys.filter((key) => {
      const meta = configurableItems.value[key]?.template_metadata?.kind
      return ['tools', 'knowledges', 'mcps', 'skills', 'subagents'].includes(meta)
    }),
    other: keys.filter((key) => {
      const meta = configurableItems.value[key]?.template_metadata?.kind
      return !['llm', 'prompt', 'tools', 'knowledges', 'mcps', 'skills', 'subagents'].includes(meta)
    })
  }
})

const filteredConfigurableItems = computed(() => {
  if (isEmptyConfig.value) return {}
  const keys = segmentConfigKeys.value[currentSegment.value] || []
  const filtered = {}
  keys.forEach((key) => {
    filtered[key] = configurableItems.value[key]
  })
  return filtered
})

const configSwitchOptions = computed(() => {
  if (!selectedAgentId.value) return []
  const list = agentConfigs.value[selectedAgentId.value] || []
  const options = list.map((cfg) => ({
    label: cfg.is_default ? `${cfg.name} (default)` : cfg.name,
    value: cfg.id
  }))

  if (userStore.isAdmin) {
    options.push({
      label: '+ Create config',
      value: CREATE_CONFIG_OPTION_VALUE
    })
  }

  return options
})

const loadLiveSkillOptions = async (force = false) => {
  if (!userStore.isAdmin) {
    liveSkillOptions.value = []
    return
  }
  // Skip if not forced and data already exists
  if (!force && liveSkillOptions.value.length > 0) {
    return
  }
  try {
    const result = await skillApi.listSkills()
    const rows = result?.data || []
    liveSkillOptions.value = rows.map((item) => ({
      id: item.slug,
      name: item.slug,
      description: item.description || ''
    }))
  } catch (error) {
    console.warn('Failed to load live Skills list:', error)
  }
}

const loadMcpOptions = async (force = false) => {
  if (!userStore.isAdmin) {
    liveMcpOptions.value = []
    return
  }
  if (!force && liveMcpOptions.value.length > 0) {
    return
  }
  try {
    const result = await mcpApi.getMcpServers()
    const rows = result?.data || []
    liveMcpOptions.value = rows
      .filter((item) => item?.enabled !== false)
      .map((item) => ({
        id: item.name,
        name: item.name,
        description: item.description || ''
      }))
  } catch (error) {
    console.warn('Failed to load MCP list:', error)
  }
}

const loadToolOptions = async (force = false) => {
  if (!userStore.isAdmin) {
    toolOptionsFromApi.value = []
    return
  }
  // Skip if not forced and data already exists
  if (!force && toolOptionsFromApi.value.length > 0) {
    return
  }
  try {
    const result = await toolApi.getTools()
    toolOptionsFromApi.value = (result?.data || []).map((item) => ({
      id: item.id,
      name: item.name || item.id,
      description: item.description || ''
    }))
  } catch (error) {
    console.warn('Failed to load tool list:', error)
  }
}

const loadSubagentOptions = async (force = false) => {
  if (!userStore.isAdmin) {
    liveSubagentOptions.value = []
    return
  }
  if (!force && liveSubagentOptions.value.length > 0) {
    return
  }
  try {
    const result = await subagentApi.getSubAgents()
    const rows = result?.data || []
    liveSubagentOptions.value = rows
      .filter((item) => item?.enabled !== false)
      .map((item) => ({
        id: item.name,
        name: item.name,
        description: item.description || ''
      }))
  } catch (error) {
    console.warn('Failed to load Subagents list:', error)
  }
}

// Determine whether this config type should navigate to another page
const isToolsKind = (kind) => {
  return ['knowledges', 'tools', 'mcps', 'skills', 'subagents'].includes(kind)
}

// Force refresh the option list for the corresponding config item
const refreshConfigOptions = async (_key, kind) => {
  if (isReadOnlyConfig.value) return
  try {
    switch (kind) {
      case 'knowledges':
        await databaseStore.loadDatabases(true)
        message.success('Knowledge base list refreshed')
        break
      case 'tools':
        await loadToolOptions(true)
        message.success('Tool list refreshed')
        break
      case 'skills':
        await loadLiveSkillOptions(true)
        message.success('Skills list refreshed')
        break
      case 'subagents':
        await loadSubagentOptions(true)
        message.success('Subagents list refreshed')
        break
      case 'mcps':
        await loadMcpOptions(true)
        message.success('MCP list refreshed')
        break
    }
  } catch (error) {
    console.error('Failed to refresh config options:', error)
    message.error('Refresh failed')
  }
}

// Navigate to the corresponding management page
const navigateToConfigPage = (kind) => {
  if (isReadOnlyConfig.value) return
  // Close the selection modal first
  closeSelectionModal()
  // Delay navigation to ensure the modal closes first
  setTimeout(() => {
    switch (kind) {
      case 'knowledges':
        router.push('/database')
        break
      case 'tools':
        router.push({ path: '/extensions', query: { tab: 'tools' } })
        break
      case 'mcps':
        router.push({ path: '/extensions', query: { tab: 'mcp' } })
        break
      case 'skills':
        router.push({ path: '/extensions', query: { tab: 'skills' } })
        break
      case 'subagents':
        router.push({ path: '/extensions', query: { tab: 'subagents' } })
        break
    }
  }, 100)
}

// Generic option resolution and handling
const resolveOptionValue = (option) => {
  if (typeof option === 'object' && option !== null) {
    return option.id || option.value || option.name || option.db_id || option.slug
  }
  return option
}

const getConfigOptions = (value) => {
  if (value?.template_metadata?.kind === 'tools') {
    return toolOptionsFromApi.value || []
  }
  if (value?.template_metadata?.kind === 'knowledges') {
    return databaseStore.databases || []
  }
  if (value?.template_metadata?.kind === 'mcps') {
    return liveMcpOptions.value || []
  }
  if (value?.template_metadata?.kind === 'skills') {
    return liveSkillOptions.value.length > 0 ? liveSkillOptions.value : value?.options || []
  }
  if (value?.template_metadata?.kind === 'subagents') {
    return liveSubagentOptions.value || []
  }
  return value?.options || []
}

const isListConfig = (key, value) => {
  const isTools = value?.template_metadata?.kind === 'tools'
  const isList = value?.type === 'list'
  return isTools || isList || key === 'skills' || key === 'subagents'
}

const getOptionValue = (option) => {
  return resolveOptionValue(option)
}

const getOptionLabel = (option) => {
  if (typeof option === 'object' && option !== null) {
    return option.name || option.label || option.id || option.db_id || option.slug
  }
  return option
}

const getOptionDescription = (option) => {
  if (typeof option === 'object' && option !== null) {
    return option.description || 'No description available'
  }
  return null
}

const currentConfigKind = computed(() => {
  if (!currentConfigKey.value) return null
  return configurableItems.value[currentConfigKey.value]?.template_metadata?.kind
})

const systemPromptModalTitle = computed(() => {
  if (!currentSystemPromptKey.value) return 'System Prompt'
  return configurableItems.value[currentSystemPromptKey.value]?.name || currentSystemPromptKey.value
})

const systemPromptModalPlaceholder = computed(() => {
  if (!currentSystemPromptKey.value) return 'Enter system prompt'
  const currentItem = configurableItems.value[currentSystemPromptKey.value]
  if (!currentItem) return 'Enter system prompt'
  return getPlaceholder(currentSystemPromptKey.value, currentItem)
})

const filteredOptions = computed(() => {
  if (!currentConfigKey.value) return []
  const key = currentConfigKey.value
  const configItem = configurableItems.value[key]
  const options = getConfigOptions(configItem)

  if (!selectionSearchText.value) return options

  const search = selectionSearchText.value.toLowerCase()
  return options.filter((opt) => {
    const label = String(getOptionLabel(opt)).toLowerCase()
    const desc = String(getOptionDescription(opt) || '').toLowerCase()
    return label.includes(search) || desc.includes(search)
  })
})

// Methods
const handleConfigSwitch = async (configId) => {
  if (configId === CREATE_CONFIG_OPTION_VALUE) {
    openCreateConfigModal()
    return
  }

  if (!configId || configId === selectedAgentConfigId.value) return
  try {
    await agentStore.selectAgentConfig(configId)
  } catch (error) {
    console.error('Failed to switch config:', error)
    message.error('Switch config failed')
  }
}

const updateConfigValue = (key, value) => {
  if (isReadOnlyConfig.value) return
  agentStore.updateAgentConfig({
    [key]: value
  })
}

const openCreateConfigModal = () => {
  if (!userStore.isAdmin) return
  createConfigName.value = ''
  createConfigModalOpen.value = true
}

const closeCreateConfigModal = () => {
  createConfigModalOpen.value = false
  createConfigName.value = ''
}

const handleCreateConfig = async () => {
  if (!userStore.isAdmin) return
  if (!selectedAgentId.value) return
  const name = createConfigName.value.trim()
  if (!name) {
    message.error('Enter a config name')
    return
  }

  createConfigLoading.value = true
  try {
    await agentStore.createAgentConfigProfile({
      name,
      setDefault: false,
      fromCurrent: false
    })
    closeCreateConfigModal()
    message.success('Config created')
  } catch (error) {
    console.error('Failed to create config:', error)
    message.error(error.message || 'Config creation failed')
  } finally {
    createConfigLoading.value = false
  }
}

const shouldShowConfig = () => {
  return true
}

const closeSidebar = () => {
  emit('close')
}

const getConfigLabel = (key, value) => {
  // console.log(configurableItems)
  if (value.description && value.name !== key) {
    return `${value.name}`
    // return `${value.name}（${key}）`;
  }
  return key
}

const getPlaceholder = (_key, value) => {
  return `(default: ${value.default})`
}

const handleModelChange = (key, spec) => {
  if (isReadOnlyConfig.value) return
  if (typeof spec !== 'string' || !spec) return
  agentStore.updateAgentConfig({
    [key]: spec
  })
}

// Multi-select helpers
const ensureArray = (key) => {
  const config = agentConfig.value || {}
  if (!config[key] || !Array.isArray(config[key])) {
    return []
  }
  return config[key]
}

const isOptionSelected = (key, option) => {
  const currentOptions = ensureArray(key)
  return currentOptions.includes(option)
}

const getSelectedCount = (key) => {
  const currentOptions = ensureArray(key)
  return currentOptions.length
}

const toggleOption = (key, option) => {
  if (isReadOnlyConfig.value) return
  const currentOptions = [...ensureArray(key)]
  const index = currentOptions.indexOf(option)

  if (index > -1) {
    currentOptions.splice(index, 1)
  } else {
    currentOptions.push(option)
  }

  agentStore.updateAgentConfig({
    [key]: currentOptions
  })
}

const clearSelection = (key) => {
  if (isReadOnlyConfig.value) return
  agentStore.updateAgentConfig({
    [key]: []
  })
}

// Unified selection modal helpers
const getOptionLabelFromValue = (key, val) => {
  const options = getConfigOptions(configurableItems.value[key])
  const option = options.find((opt) => getOptionValue(opt) === val)
  return option ? getOptionLabel(option) : val
}

const openSelectionModal = async (key) => {
  if (isReadOnlyConfig.value) return
  currentConfigKey.value = key
  // If this is a tool, refresh the tool list from the API
  if (configurableItems.value[key]?.template_metadata?.kind === 'tools') {
    await loadToolOptions()
  }
  // If this is a knowledge base, fetch the knowledge base list
  if (configurableItems.value[key]?.template_metadata?.kind === 'knowledges') {
    try {
      await databaseStore.loadDatabases()
    } catch (error) {
      console.error('Failed to load knowledge base list:', error)
    }
  }
  if (configurableItems.value[key]?.template_metadata?.kind === 'skills') {
    await loadLiveSkillOptions()
  }
  if (configurableItems.value[key]?.template_metadata?.kind === 'subagents') {
    await loadSubagentOptions()
  }
  const currentValues = agentConfig.value[key] || []
  tempSelectedValues.value = [...currentValues]
  selectionModalOpen.value = true
}

const toggleModalSelection = (optionValue) => {
  if (isReadOnlyConfig.value) return
  const index = tempSelectedValues.value.indexOf(optionValue)
  if (index > -1) {
    tempSelectedValues.value.splice(index, 1)
  } else {
    tempSelectedValues.value.push(optionValue)
  }
}

const confirmSelection = () => {
  if (isReadOnlyConfig.value) {
    closeSelectionModal()
    return
  }
  if (currentConfigKey.value) {
    agentStore.updateAgentConfig({
      [currentConfigKey.value]: [...tempSelectedValues.value]
    })
  }
  closeSelectionModal()
}

const closeSelectionModal = () => {
  selectionModalOpen.value = false
  currentConfigKey.value = null
  tempSelectedValues.value = []
  selectionSearchText.value = ''
}

// System prompt modal editing helpers
const openSystemPromptModal = (key) => {
  currentSystemPromptKey.value = key
  systemPromptDraft.value = agentConfig.value[key] || ''
  systemPromptModalOpen.value = true
}

const closeSystemPromptModal = () => {
  systemPromptModalOpen.value = false
  currentSystemPromptKey.value = null
  systemPromptDraft.value = ''
}

const saveSystemPrompt = () => {
  if (isReadOnlyConfig.value) return
  if (!currentSystemPromptKey.value) return
  agentStore.updateAgentConfig({
    [currentSystemPromptKey.value]: systemPromptDraft.value
  })
  closeSystemPromptModal()
}

// Validate and filter configuration items
const validateAndFilterConfig = () => {
  const validatedConfig = { ...agentConfig.value }
  const configItems = configurableItems.value

  // Iterate over all configuration items
  Object.keys(configItems).forEach((key) => {
    const configItem = configItems[key]
    const currentValue = validatedConfig[key]

    if (
      Array.isArray(currentValue) &&
      (configItem.template_metadata?.kind === 'tools' || configItem.type === 'list')
    ) {
      const options = getConfigOptions(configItem)
      const validValues = new Set(options.map((opt) => String(getOptionValue(opt))))
      if (validValues.size === 0) return

      validatedConfig[key] = currentValue.filter((value) => validValues.has(String(value)))
      if (validatedConfig[key].length !== currentValue.length) {
        console.warn(`Invalid options found in config item ${key}; filtered automatically`)
      }
    }
  })

  return validatedConfig
}

// Config save and reset
const saveConfig = async () => {
  if (!selectedAgentId.value) {
    message.error('No agent selected')
    return
  }

  if (!agentStore.hasConfigChanges) return

  try {
    isSavingConfig.value = true
    // Validate and filter configuration
    const validatedConfig = validateAndFilterConfig()

    // If the configuration changed, update the store first
    if (JSON.stringify(validatedConfig) !== JSON.stringify(agentConfig.value)) {
      agentStore.updateAgentConfig(validatedConfig)
      message.info('Invalid configuration items detected and filtered automatically')
    }

    await agentStore.saveAgentConfig()
    message.success('Configuration saved to server')
  } catch (error) {
    console.error('Failed to save configuration to server:', error)
    message.error('Failed to save configuration to server')
  } finally {
    isSavingConfig.value = false
  }
}

const setAsDefault = async () => {
  if (!selectedAgentId.value || !selectedAgentConfigId.value) return
  try {
    await agentStore.setSelectedAgentConfigDefault()
    message.success('Set as default configuration')
  } catch (error) {
    console.error('Failed to set default configuration:', error)
    message.error('Failed to set default configuration')
  }
}

const confirmDeleteConfig = async () => {
  if (!selectedAgentId.value || !selectedAgentConfigId.value) return

  const currentName = selectedConfigSummary.value?.name || 'Current config'
  const list = agentConfigs.value[selectedAgentId.value] || []
  const content =
    list.length <= 1
      ? `This will delete "${currentName}". After deletion, the system will automatically create a new default configuration.`
      : `This will delete "${currentName}".`

  Modal.confirm({
    title: 'Confirm config deletion?',
    content,
    okText: 'Delete',
    okType: 'danger',
    cancelText: 'Cancel',
    onOk: async () => {
      isDeletingConfig.value = true
      try {
        await agentStore.deleteSelectedAgentConfigProfile()
        message.success('Config deleted')
      } catch (error) {
        console.error('Failed to delete config:', error)
        message.error('Failed to delete config')
      } finally {
        isDeletingConfig.value = false
      }
    }
  })
}
</script>

<style lang="less" scoped>
.agent-config-sidebar {
  position: relative;
  width: 0;
  height: 100vh;
  background: var(--gray-0);
  border-left: 1px solid var(--gray-200);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;

  &.open {
    width: 400px;
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    padding: 0 12px;
    height: var(--header-height);
    border-bottom: 1px solid var(--gray-150);
    background: var(--gray-0);
    flex-shrink: 0;
    min-width: 400px;
    z-index: 10;

    .header-top-row {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
    }

    .config-manage-row {
      display: flex;
      align-items: center;
      flex: 1;
      min-width: 0;

      .config-switch-select {
        flex: 1;
        min-width: 0;

        :deep(.ant-select-selector) {
          height: 32px;
          border-radius: 8px;
          border-color: var(--gray-200);
          padding: 0 10px;
          transition: border-color 0.2s ease;
        }

        :deep(.ant-select-selection-search-input),
        :deep(.ant-select-selection-item),
        :deep(.ant-select-selection-placeholder) {
          line-height: 30px;
          font-size: 13px;
        }

        :deep(.ant-select.ant-select-focused .ant-select-selector),
        :deep(.ant-select-selector:hover) {
          border-color: var(--main-color);
          box-shadow: none;
        }
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
    }
  }

  .icon-btn {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    color: var(--gray-600);
    border: 1px solid var(--gray-200);
    background: var(--gray-0);
    padding: 0;
    transition:
      color 0.2s ease,
      border-color 0.2s ease,
      background-color 0.2s ease;

    &:hover:not(:disabled) {
      color: var(--main-600);
      border-color: var(--main-200);
      background: var(--main-10);
    }

    &.is-default {
      color: var(--color-warning-500);
    }

    &.ant-btn-dangerous:hover:not(:disabled) {
      color: var(--color-error-700);
      border-color: var(--color-error-100);
      background: var(--color-error-50);
    }

    &:disabled {
      cursor: not-allowed;
      background: transparent;
      color: var(--gray-400);
      border-color: var(--gray-200);

      &.is-default {
        opacity: 1;
      }
    }
  }

  .sidebar-content {
    flex: 1;
    overflow-y: auto;
    padding: 10px 12px 8px;
    min-width: 400px;

    .agent-info {
      .agent-basic-info {
        .agent-description {
          margin: 0 0 12px 0;
          font-size: 14px;
          color: var(--gray-700);
          line-height: 1.5;
        }
      }
    }

    .config-segment {
      margin: 0 auto;
      margin-bottom: 6px;
      padding: 4px 0;
      width: 80%;
    }

    .config-form-content {
      margin-bottom: 20px;

      &.is-readonly {
        .config-item {
          background: var(--gray-20);

          .model-selector.is-readonly {
            opacity: 0.78;
            pointer-events: none;
          }

          .system-prompt-display {
            cursor: default;

            &:hover {
              border-color: var(--gray-200);
              background: transparent;

              .edit-hint {
                opacity: 1;
              }
            }

            .edit-hint {
              color: var(--gray-500);
              opacity: 1;
            }
          }

          .option-card.readonly {
            cursor: default;

            &:hover {
              border-color: var(--gray-300);
              background: var(--gray-0);
            }

            &.selected:hover {
              border-color: var(--main-color);
              background: var(--main-10);
            }
          }
        }
      }

      .config-form {
        .config-alert {
          margin-bottom: 16px;
        }

        .config-item {
          background-color: var(--gray-25);
          padding: 12px;
          border-radius: 8px;
          border: 1px solid var(--gray-100);
          // box-shadow: 0px 0px 2px var(--shadow-3);

          :deep(.ant-form-item-label > label) {
            font-weight: 600;
          }

          :deep(label.form_item_model) {
            font-weight: 600;
          }

          .config-description {
            margin: 4px 0 8px 0;
            font-size: 12px;
            color: var(--gray-600);
            line-height: 1.4;
          }

          .model-selector {
            width: 100%;
          }

          .system-prompt-container {
            width: 100%;
          }

          .system-prompt-display {
            min-height: 60px;
            border: 1px solid var(--gray-200);
            padding: 10px 12px;
            border-radius: 6px;
            cursor: pointer;
            position: relative;
            transition: all 0.2s ease;

            &:hover {
              border-color: var(--main-color);
              background: var(--gray-25);

              .edit-hint {
                opacity: 1;
              }
            }

            .system-prompt-content {
              white-space: pre-line;
              word-break: break-word;
              line-height: 1.5;
              color: var(--gray-900);
              font-size: 13px;
              display: -webkit-box;
              line-clamp: 4;
              -webkit-line-clamp: 4;
              -webkit-box-orient: vertical;
              overflow: hidden;

              &.is-placeholder {
                color: var(--gray-400);
                font-style: italic;
              }
            }

            .edit-hint {
              position: absolute;
              top: -32px;
              right: 0px;
              font-size: 12px;
              color: var(--main-800);
              opacity: 0;
              transition: opacity 0.2s ease;
              background: var(--gray-0);
              padding: 2px 6px;
              border-radius: 4px;
            }
          }

          .config-select,
          .config-input,
          .config-input-number {
            width: 100%;
          }

          .config-slider {
            width: 100%;
          }
        }
      }
    }
  }

  .sidebar-footer {
    padding: 8px 12px;
    border-top: 1px solid var(--gray-100);
    background: var(--gray-0);
    // min-width: 400px;
    z-index: 10;
    flex-shrink: 0; // Ensure footer doesn't shrink

    .form-actions {
      display: flex;
      gap: 10px;
      align-items: center;

      .footer-main-btn {
        width: 100%;
        height: 36px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        transition:
          opacity 0.2s ease,
          border-color 0.2s ease,
          background-color 0.2s ease,
          color 0.2s ease;
      }

      .save-btn {
        background-color: var(--gray-100);
        border: 1px solid var(--gray-200);
        color: var(--gray-600);

        &.changed {
          background-color: var(--main-color);
          color: var(--gray-0);
          border-color: var(--main-color);
        }

        &:hover:not(:disabled) {
          opacity: 0.9;
        }

        &:disabled {
          cursor: not-allowed;
          background-color: var(--gray-100);
          border-color: var(--gray-200);
          color: var(--gray-400);
        }
      }
    }
  }
}

// Selector styles
.selection-container {
  .selection-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 10px;
    background: var(--gray-0);
    border-radius: 8px;
    border: 1px solid var(--gray-150);
    margin-bottom: 8px;

    .selection-summary-info {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--gray-900);

      .selection-count {
        color: var(--gray-900);
        font-weight: 500;
      }
    }

    .selection-trigger-btn {
      border-radius: 4px;
      height: 28px;
      font-size: 12px;
      font-weight: 500;
    }
  }

  .selection-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;

    .selection-tag {
      margin: 0;
      padding: 4px 8px;
      border-radius: 8px;
      background: var(--gray-150);
      border: none;
      color: var(--gray-900);
      font-size: 12px;

      :deep(.anticon-close) {
        color: var(--gray-600);
        margin-left: 4px;

        &:hover {
          color: var(--gray-900);
        }
      }
    }
  }
}

// Multi-select card styles
.multi-select-cards {
  .multi-select-label {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    font-size: 12px;
    color: var(--gray-600);

    .label-actions {
      display: flex;
      align-items: center;
      gap: 4px;
    }
  }

  .options-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .option-card {
    border: 1px solid var(--gray-300);
    border-radius: 8px;
    padding: 8px 12px;
    cursor: pointer;
    transition: all 0.2s ease;
    background: var(--gray-0);

    &:hover {
      border-color: var(--main-color);
    }

    &.selected {
      border-color: var(--main-color);
      background: var(--main-10);

      .option-indicator {
        color: var(--main-color);
      }

      .option-text {
        color: var(--main-color);
        font-weight: 500;
      }
    }

    &.unselected {
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
      gap: 8px;

      .option-text {
        flex: 1;
        font-size: 13px;
        line-height: 1.4;
      }

      .option-indicator {
        flex-shrink: 0;
        font-size: 14px;
        display: flex;
        align-items: center;
      }
    }
  }
}

// Selection modal styles
.selection-modal {
  .selection-modal-content {
    .selection-search {
      margin-bottom: 16px;
      display: flex;
      gap: 8px;
      align-items: center;

      .search-input {
        flex: 1;
        border-radius: 8px;
        border: 1px solid var(--gray-300);
        height: 36px;
        font-size: 14px;
        transition: all 0.2s ease;
        background: var(--gray-0);

        .search-icon {
          color: var(--gray-500);
          font-size: 16px;
        }

        &:focus-within {
          border-color: var(--main-color);
          box-shadow: 0 0 0 2px rgba(1, 97, 121, 0.1);

          .search-icon {
            color: var(--main-color);
          }
        }

        &:hover {
          border-color: var(--gray-400);
        }
      }
    }

    .selection-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      max-height: 60vh;
      overflow-y: auto;
      border-radius: 8px;
      margin-bottom: 16px;

      // Switch to a single-column layout on small screens
      @media (max-width: 480px) {
        grid-template-columns: 1fr;
      }

      .selection-item {
        padding: 12px 16px;
        cursor: pointer;
        transition: all 0.2s ease;
        border-radius: 8px;
        background: var(--gray-0);
        border: 1px solid var(--gray-200);

        &:hover {
          border-color: var(--gray-300);
          background: var(--gray-20);
        }
        .selection-item-content {
          .selection-item-header {
            display: flex;
            align-items: center;
            gap: 8px;

            .selection-item-name {
              font-size: 14px;
              font-weight: 500;
              color: var(--gray-900);
              line-height: 1.3;
              flex: 1;
            }

            .selection-item-indicator {
              color: var(--gray-400);
              font-size: 16px;
              transition: all 0.2s ease;
              flex-shrink: 0;
              display: flex;
              align-items: center;
            }
          }

          .selection-item-description {
            font-size: 12px;
            color: var(--gray-600);
            line-height: 1.4;
            margin-top: 6px;
            display: -webkit-box;
            line-clamp: 2;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
          }
        }

        &.selected {
          background: var(--main-10);
          border-color: var(--main-color);

          .selection-item-content {
            .selection-item-name {
              color: var(--main-800);
            }
            .selection-item-indicator {
              color: var(--main-800);
            }
          }
          .selection-item-description {
            color: var(--gray-900);
          }
        }
      }
    }

    .selection-modal-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 16px;
      border-top: 1px solid var(--gray-200);

      .selected-count {
        font-size: 14px;
        color: var(--gray-700);
        font-weight: 500;
        padding: 6px 12px;
        background: var(--gray-50);
        border-radius: 8px;
        border: 1px solid var(--gray-200);
      }

      .modal-actions {
        display: flex;
        gap: 12px;

        :deep(.ant-btn) {
          border-radius: 8px;
          height: 36px;
          font-size: 14px;
          font-weight: 500;
          padding: 0 16px;
          transition: all 0.2s ease;

          &.ant-btn-default {
            border: 1px solid var(--gray-300);
            color: var(--gray-700);
            background: var(--gray-0);

            &:hover {
              border-color: var(--main-color);
              color: var(--main-color);
            }
          }

          &.ant-btn-primary {
            background: var(--main-color);
            border: none;
            color: var(--gray-0);

            &:hover {
              background: var(--main-color);
              opacity: 0.9;
            }
          }
        }
      }
    }
  }
}

.system-prompt-modal {
  .system-prompt-modal-content {
    .system-prompt-modal-input {
      resize: vertical;
      font-size: 13px;
      line-height: 1.6;
      border-radius: 8px;
    }
  }
}

.clear-btn {
  padding: 0;
  height: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--main-700);

  &:hover {
    color: var(--main-800);
  }
}

.inline-action-btn {
  padding: 2px 6px;
  height: auto;
  line-height: 1;
  font-size: 12px;
  color: var(--gray-600);
  white-space: nowrap;

  &:hover {
    color: var(--main-color);
  }
}

.selection-search .inline-action-btn {
  font-size: 13px;
}

// Responsive adjustments
@media (max-width: 768px) {
  .agent-config-sidebar.open {
    width: 100%;
  }

  .sidebar-header,
  .sidebar-content {
    min-width: 100% !important;
  }
}
</style>
