import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { brandApi } from '@/apis/system_api'

export const useInfoStore = defineStore('info', () => {
  // State
  const infoConfig = ref({})
  const isLoading = ref(false)
  const isLoaded = ref(false)
  const debugMode = ref(false)

  // Computed - Organization Info
  const organization = computed(
    () =>
      infoConfig.value.organization || {
        name: 'Yunesa',
        logo: '',
        avatar: ''
      }
  )

  // Computed - Branding Info
  const branding = computed(
    () =>
      infoConfig.value.branding || {
        name: 'Yunesa',
        title: 'Yunesa Knowledge Engine',
        subtitle: 'Intelligent Agent & Knowledge Management Platform',
        subtitles: ['Yunesa Agent Terminal', 'Strategic Knowledge Management']
      }
  )

  // Computed - Features
  const features = computed(() => infoConfig.value.features || [])

  const actions = computed(() => infoConfig.value.actions || [])

  // Computed - Footer Info
  const footer = computed(() => ({
    copyright: '',
    user_agreement_url: '',
    privacy_policy_url: '',
    ...(infoConfig.value.footer || {})
  }))

  // Actions
  function setInfoConfig(newConfig) {
    infoConfig.value = newConfig
    isLoaded.value = true
  }

  function setDebugMode(enabled) {
    debugMode.value = enabled
  }

  function toggleDebugMode() {
    debugMode.value = !debugMode.value
  }

  async function loadInfoConfig(force = false) {
    // If already loaded and refresh is not forced, do not reload
    if (isLoaded.value && !force) {
      return infoConfig.value
    }

    try {
      isLoading.value = true
      const response = await brandApi.getInfoConfig()

      if (response.success && response.data) {
        setInfoConfig(response.data)
        console.debug('Info config loaded successfully:', response.data)
        return response.data
      } else {
        console.warn('Failed to load info config, using default branding')
        return null
      }
    } catch (error) {
      console.error('Error occurred while loading info config:', error)
      return null
    } finally {
      isLoading.value = false
    }
  }

  async function reloadInfoConfig() {
    try {
      isLoading.value = true
      const response = await brandApi.reloadInfoConfig()

      if (response.success && response.data) {
        setInfoConfig(response.data)
        console.debug('Info config reloaded successfully:', response.data)
        return response.data
      } else {
        console.warn('Failed to reload info config')
        return null
      }
    } catch (error) {
      console.error('Error occurred while reloading info config:', error)
      return null
    } finally {
      isLoading.value = false
    }
  }

  return {
    // State
    infoConfig,
    isLoading,
    isLoaded,
    debugMode,

    // Computed properties
    organization,
    branding,
    features,
    footer,
    actions,

    // Methods
    setInfoConfig,
    setDebugMode,
    toggleDebugMode,
    loadInfoConfig,
    reloadInfoConfig
  }
})
