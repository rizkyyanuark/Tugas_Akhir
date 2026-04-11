import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatUIStore = defineStore('chatUI', () => {
  // ==================== Chat Interface UI State ====================
  // Conversation list sidebar state
  const isSidebarOpen = ref(localStorage.getItem('chat_sidebar_open') !== 'false')

  // Loading states
  const creatingNewChat = ref(false)
  const isLoadingThreads = ref(false)
  const isLoadingMessages = ref(false)

  // ==================== AgentView UI State ====================
  // Agent selection modal
  const agentModalOpen = ref(false)

  // Configuration sidebar
  const isConfigSidebarOpen = ref(false)

  // More menu
  const moreMenuOpen = ref(false)
  const moreMenuPosition = ref({ x: 0, y: 0 })

  // ==================== Methods ====================
  /**
   * Toggle conversation list sidebar
   */
  function toggleSidebar() {
    isSidebarOpen.value = !isSidebarOpen.value
    localStorage.setItem('chat_sidebar_open', String(isSidebarOpen.value))
  }

  /**
   * Open more menu
   * @param {number} x - X coordinate
   * @param {number} y - Y coordinate
   */
  function openMoreMenu(x, y) {
    moreMenuPosition.value = { x, y }
    moreMenuOpen.value = true
  }

  /**
   * Close more menu
   */
  function closeMoreMenu() {
    moreMenuOpen.value = false
  }

  /**
   * Reset all UI states (excluding persisted states)
   */
  function reset() {
    creatingNewChat.value = false
    isLoadingThreads.value = false
    isLoadingMessages.value = false
    agentModalOpen.value = false
    isConfigSidebarOpen.value = false
    moreMenuOpen.value = false
    moreMenuPosition.value = { x: 0, y: 0 }
  }

  return {
    // States
    isSidebarOpen,
    creatingNewChat,
    isLoadingThreads,
    isLoadingMessages,
    agentModalOpen,
    isConfigSidebarOpen,
    moreMenuOpen,
    moreMenuPosition,

    // Methods
    toggleSidebar,
    openMoreMenu,
    closeMoreMenu,
    reset
  }
})
