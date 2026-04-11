import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { agentApi, databaseApi, mcpApi, skillApi } from '@/apis'
import { handleChatError } from '@/utils/errorHandler'
import { useUserStore } from '@/stores/user'

export const useAgentStore = defineStore(
  'agent',
  () => {
    // ==================== State Definition ====================
    // Agent related states
    const agents = ref([])
    const selectedAgentId = ref(null)
    const defaultAgentId = ref(null)

    // Resource related states
    const availableKnowledgeBases = ref([])
    const availableMcps = ref([])
    const availableSkills = ref([])

    // Agent configuration related states
    const agentConfig = ref({})
    const originalAgentConfig = ref({})
    const agentConfigs = ref({})
    const selectedAgentConfigId = ref(null)

    const agentDetails = ref({}) // Store detailed information for each agent (including configurable_items)

    // Loading states
    const isLoadingAgents = ref(false)
    const isLoadingConfig = ref(false)
    const isLoadingAgentConfigs = ref(false)
    const isLoadingAgentDetail = ref(false)

    // Initialization states
    const isInitialized = ref(false)
    const isInitializing = ref(false)
    const error = ref(null)

    // ==================== Computed Properties ====================
    const selectedAgent = computed(() =>
      selectedAgentId.value ? agents.value.find((a) => a.id === selectedAgentId.value) : null
    )

    const defaultAgent = computed(() =>
      defaultAgentId.value
        ? agents.value.find((a) => a.id === defaultAgentId.value)
        : agents.value[0]
    )

    const agentsList = computed(() => agents.value)

    const isDefaultAgent = computed(() => selectedAgentId.value === defaultAgentId.value)

    const configurableItems = computed(() => {
      const agentId = selectedAgentId.value
      if (
        !agentId ||
        !agentDetails.value[agentId] ||
        !agentDetails.value[agentId].configurable_items
      ) {
        return {}
      }

      const agentConfigurableItems = agentDetails.value[agentId].configurable_items
      const items = { ...agentConfigurableItems }
      Object.keys(items).forEach((key) => {
        const item = items[key]
        if (item && item.x_oap_ui_config) {
          items[key] = { ...item, ...item.x_oap_ui_config }
          delete items[key].x_oap_ui_config
        }
      })
      return items
    })

    // Tool related states
    const availableTools = computed(() => {
      return configurableItems.value.tools?.options || []
    })

    const hasConfigChanges = computed(
      () => JSON.stringify(agentConfig.value) !== JSON.stringify(originalAgentConfig.value)
    )

    const selectedConfigSummary = computed(() => {
      const agentId = selectedAgentId.value
      const configId = selectedAgentConfigId.value
      if (!agentId || !configId) return null
      const list = agentConfigs.value[agentId] || []
      return list.find((c) => c.id === configId) || null
    })

    // ==================== Methods ====================
    /**
     * Fetch mentionable resources (Knowledge Base, MCP, Skills)
     */
    async function fetchMentionResources() {
      try {
        const [dbsRes, mcpsRes, skillsRes] = await Promise.all([
          databaseApi.getAccessibleDatabases().catch(() => ({ databases: [] })),
          mcpApi.getMcpServers().catch(() => ({ data: [] })),
          skillApi.listSkills().catch(() => ({ data: [] }))
        ])
        availableKnowledgeBases.value = dbsRes.databases || []
        availableMcps.value = mcpsRes.data || []
        availableSkills.value = skillsRes.data || []
      } catch (e) {
        console.warn('Failed to fetch mention resources:', e)
      }
    }

    /**
     * Initialize store
     */
    async function initialize() {
      if (isInitialized.value) return

      // Prevent concurrent initialization
      if (isInitializing.value) return
      isInitializing.value = true

      try {
        await fetchAgents()
        await fetchDefaultAgent()
        await fetchMentionResources()

        if (!selectedAgent.value) {
          if (defaultAgent.value) {
            await selectAgent(defaultAgentId.value)
          } else if (agents.value.length > 0) {
            const firstAgentId = agents.value[0].id
            await selectAgent(firstAgentId)
          }
        } else {
          console.log('Condition FALSE: Persisted selected agent is valid. Keeping it.')
          // Ensure cached agent details exist
          if (selectedAgentId.value && !agentDetails.value[selectedAgentId.value]) {
            try {
              await fetchAgentDetail(selectedAgentId.value)
            } catch (err) {
              console.warn(`Failed to fetch agent detail for ${selectedAgentId.value}:`, err)
            }
          }

          if (selectedAgentId.value) {
            try {
              await fetchAgentConfigs(selectedAgentId.value)
              const list = agentConfigs.value[selectedAgentId.value] || []
              const persistedId = selectedAgentConfigId.value
              const persistedItem = persistedId ? list.find((c) => c.id === persistedId) : null
              const defaultItem = list.find((c) => c.is_default) || list[0]
              const pickId = (persistedItem || defaultItem)?.id || null
              selectedAgentConfigId.value = pickId
              if (pickId) {
                await loadAgentConfig(selectedAgentId.value, pickId)
              }
            } catch (err) {
              console.warn(`Failed to init agent configs for ${selectedAgentId.value}:`, err)
            }
          }
        }

        isInitialized.value = true
      } catch (err) {
        console.error('Failed to initialize agent store:', err)
        handleChatError(err, 'initialize')
        error.value = err.message
      } finally {
        isInitializing.value = false
      }
    }

    /**
     * Fetch agent list
     */
    async function fetchAgents() {
      isLoadingAgents.value = true
      error.value = null

      try {
        const response = await agentApi.getAgents()
        agents.value = response.agents
      } catch (err) {
        console.error('Failed to fetch agents:', err)
        handleChatError(err, 'fetch')
        error.value = err.message
        throw err
      } finally {
        isLoadingAgents.value = false
      }
    }

    /**
     * Fetch detailed information of a single agent (including configuration options)
     * @param {string} agentId - Agent ID
     */
    async function fetchAgentDetail(agentId, forceRefresh = false) {
      if (!agentId) return

      // If details are already cached and no forced refresh, return directly
      if (!forceRefresh && agentDetails.value[agentId]) {
        return agentDetails.value[agentId]
      }

      isLoadingAgentDetail.value = true
      error.value = null

      try {
        const response = await agentApi.getAgentDetail(agentId)
        agentDetails.value[agentId] = response
        // availableTools.value[agentId] = response.available_tools || []
        return response
      } catch (err) {
        console.error(`Failed to fetch agent detail for ${agentId}:`, err)
        handleChatError(err, 'fetch')
        error.value = err.message
        throw err
      } finally {
        isLoadingAgentDetail.value = false
      }
    }

    /**
     * Fetch default agent
     */
    async function fetchDefaultAgent() {
      try {
        const response = await agentApi.getDefaultAgent()
        defaultAgentId.value = response.default_agent_id
      } catch (err) {
        console.error('Failed to fetch default agent:', err)
        handleChatError(err, 'fetch')
        error.value = err.message
      }
    }

    /**
     * Set default agent
     */
    async function setDefaultAgent(agentId) {
      try {
        await agentApi.setDefaultAgent(agentId)
        defaultAgentId.value = agentId
      } catch (err) {
        console.error('Failed to set default agent:', err)
        handleChatError(err, 'save')
        error.value = err.message
        throw err
      }
    }

    /**
     * Select agent
     */
    async function selectAgent(agentId) {
      if (agents.value.find((a) => a.id === agentId)) {
        selectedAgentId.value = agentId
        // Clear previous configuration
        agentConfig.value = {}
        originalAgentConfig.value = {}
        selectedAgentConfigId.value = null

        // Fetch agent details and configuration list in parallel
        await Promise.all([
          (async () => {
            try {
              await fetchAgentDetail(agentId)
            } catch (err) {
              console.warn(`Failed to fetch agent detail for ${agentId}:`, err)
            }
          })(),
          (async () => {
            try {
              await fetchAgentConfigs(agentId)
              const list = agentConfigs.value[agentId] || []
              const defaultItem = list.find((c) => c.is_default) || list[0]
              selectedAgentConfigId.value = defaultItem ? defaultItem.id : null
              if (selectedAgentConfigId.value) {
                await loadAgentConfig(agentId, selectedAgentConfigId.value)
              }
            } catch (err) {
              console.warn(`Failed to fetch agent configs for ${agentId}:`, err)
            }
          })()
        ])
      }
    }

    /**
     * Load agent configuration
     */
    async function fetchAgentConfigs(agentId = null) {
      const targetAgentId = agentId || selectedAgentId.value
      if (!targetAgentId) return

      isLoadingAgentConfigs.value = true
      error.value = null

      try {
        const response = await agentApi.getAgentConfigs(targetAgentId)
        agentConfigs.value[targetAgentId] = response.configs || []
      } catch (err) {
        console.error('Failed to load agent configs:', err)
        handleChatError(err, 'load')
        error.value = err.message
        throw err
      } finally {
        isLoadingAgentConfigs.value = false
      }
    }

    async function loadAgentConfig(agentId = null, configId = null) {
      const targetAgentId = agentId || selectedAgentId.value
      const targetConfigId = configId || selectedAgentConfigId.value
      if (!targetAgentId || !targetConfigId) return

      isLoadingConfig.value = true
      error.value = null

      try {
        const response = await agentApi.getAgentConfigProfile(targetAgentId, targetConfigId)
        const configJson = response.config?.config_json || {}
        const contextConfig = configJson.context || configJson
        const loadedConfig = { ...contextConfig }

        // Ensure configurableItems are loaded
        if (!agentDetails.value[targetAgentId]) {
          await fetchAgentDetail(targetAgentId)
        }

        // Complete missing configuration items using default values from configurableItems
        const items = configurableItems.value
        Object.keys(items).forEach((key) => {
          const item = items[key]
          if (loadedConfig[key] === undefined || loadedConfig[key] === null) {
            // Only set if default value exists
            if (item.default !== undefined) {
              loadedConfig[key] = item.default
            }
          }

          if (
            loadedConfig[key] !== undefined &&
            loadedConfig[key] !== null &&
            loadedConfig[key] !== '' &&
            (item?.type === 'number' || item?.type === 'int' || item?.type === 'float')
          ) {
            const numericValue = Number(loadedConfig[key])
            if (!Number.isNaN(numericValue)) {
              loadedConfig[key] = item.type === 'int' ? Math.trunc(numericValue) : numericValue
            }
          }
        })

        agentConfig.value = loadedConfig
        originalAgentConfig.value = { ...loadedConfig }
      } catch (err) {
        console.error('Failed to load agent config profile:', err)
        handleChatError(err, 'load')
        error.value = err.message
        throw err
      } finally {
        isLoadingConfig.value = false
      }
    }

    async function selectAgentConfig(configId) {
      const targetAgentId = selectedAgentId.value
      if (!targetAgentId || !configId) return
      selectedAgentConfigId.value = configId
      await loadAgentConfig(targetAgentId, configId)
    }

    /**
     * Save agent configuration
     * @param {Object} options - Extra parameters (e.g., { reload_graph: true })
     */
    // eslint-disable-next-line no-unused-vars
    async function saveAgentConfig(options = {}) {
      const targetAgentId = selectedAgentId.value
      const targetConfigId = selectedAgentConfigId.value
      if (!targetAgentId || !targetConfigId) return
      if (!useUserStore().isAdmin) return

      try {
        await agentApi.updateAgentConfigProfile(targetAgentId, targetConfigId, {
          config_json: { context: agentConfig.value }
        })
        originalAgentConfig.value = { ...agentConfig.value }
      } catch (err) {
        console.error('Failed to save agent config:', err)
        handleChatError(err, 'save')
        error.value = err.message
        throw err
      }
    }

    async function createAgentConfigProfile({ name, setDefault = false, fromCurrent = true } = {}) {
      const targetAgentId = selectedAgentId.value
      if (!targetAgentId) return null
      if (!useUserStore().isAdmin) return null
      if (!name) throw new Error('Configuration name cannot be empty')

      const baseContext = fromCurrent ? { ...agentConfig.value } : {}

      const response = await agentApi.createAgentConfigProfile(targetAgentId, {
        name,
        config_json: { context: baseContext },
        set_default: setDefault
      })

      await fetchAgentConfigs(targetAgentId)
      const created = response?.config
      if (created?.id) {
        await selectAgentConfig(created.id)
      }
      return created
    }

    async function deleteSelectedAgentConfigProfile() {
      const targetAgentId = selectedAgentId.value
      const targetConfigId = selectedAgentConfigId.value
      if (!targetAgentId || !targetConfigId) return
      if (!useUserStore().isAdmin) return

      await agentApi.deleteAgentConfigProfile(targetAgentId, targetConfigId)
      await fetchAgentConfigs(targetAgentId)
      const list = agentConfigs.value[targetAgentId] || []
      const defaultItem = list.find((c) => c.is_default) || list[0]
      selectedAgentConfigId.value = defaultItem ? defaultItem.id : null
      if (selectedAgentConfigId.value) {
        await loadAgentConfig(targetAgentId, selectedAgentConfigId.value)
      } else {
        agentConfig.value = {}
        originalAgentConfig.value = {}
      }
    }

    async function setSelectedAgentConfigDefault() {
      const targetAgentId = selectedAgentId.value
      const targetConfigId = selectedAgentConfigId.value
      if (!targetAgentId || !targetConfigId) return
      if (!useUserStore().isAdmin) return

      await agentApi.setAgentConfigDefault(targetAgentId, targetConfigId)
      await fetchAgentConfigs(targetAgentId)
    }

    /**
     * Reset agent configuration
     */
    function resetAgentConfig() {
      agentConfig.value = { ...originalAgentConfig.value }
    }

    /**
     * Update configuration item
     */
    function updateConfigItem(key, value) {
      agentConfig.value[key] = value
    }

    /**
     * Update agent configuration (supports batch updates)
     */
    function updateAgentConfig(updates) {
      Object.assign(agentConfig.value, updates)
    }

    /**
     * Clear error status
     */
    function clearError() {
      error.value = null
    }

    /**
     * Reset store state
     */
    function reset() {
      agents.value = []
      selectedAgentId.value = null
      defaultAgentId.value = null
      availableKnowledgeBases.value = []
      availableMcps.value = []
      availableSkills.value = []
      agentConfig.value = {}
      originalAgentConfig.value = {}
      agentConfigs.value = {}
      selectedAgentConfigId.value = null
      agentDetails.value = {}
      isLoadingAgents.value = false
      isLoadingConfig.value = false
      isLoadingAgentConfigs.value = false
      isLoadingAgentDetail.value = false
      error.value = null
      isInitialized.value = false
      isInitializing.value = false
    }

    return {
      // State
      agents,
      selectedAgentId,
      defaultAgentId,
      availableKnowledgeBases,
      availableMcps,
      availableSkills,
      agentConfig,
      originalAgentConfig,
      agentDetails,
      isLoadingAgents,
      isLoadingConfig,
      isLoadingAgentDetail,
      isLoadingAgentConfigs,
      error,
      isInitialized,

      // Computed properties
      selectedAgent,
      defaultAgent,
      agentsList,
      isDefaultAgent,
      configurableItems,
      availableTools,
      hasConfigChanges,
      agentConfigs,
      selectedAgentConfigId,
      selectedConfigSummary,

      // Methods
      initialize,
      fetchAgents,
      fetchAgentDetail,
      fetchDefaultAgent,
      fetchMentionResources,
      setDefaultAgent,
      selectAgent,
      selectAgentConfig,
      fetchAgentConfigs,
      loadAgentConfig,
      saveAgentConfig,
      createAgentConfigProfile,
      deleteSelectedAgentConfigProfile,
      setSelectedAgentConfigDefault,
      resetAgentConfig,
      updateConfigItem,
      updateAgentConfig,
      clearError,
      reset
    }
  },
  {
    // Persistence configuration
    persist: {
      key: 'agent-store',
      storage: localStorage,
      pick: ['selectedAgentId', 'selectedAgentConfigId']
    }
  }
)
