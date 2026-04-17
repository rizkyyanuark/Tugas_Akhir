import { ref } from 'vue'
import { defineStore } from 'pinia'
import { theme } from 'ant-design-vue'

export const useThemeStore = defineStore('theme', () => {
  // Read the saved theme from localStorage, defaulting to light mode
  const isDark = ref(localStorage.getItem('theme') === 'dark')

  // Shared theme configuration
  const commonTheme = {
    token: {
      fontFamily:
        "'HarmonyOS Sans SC', Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;",
      colorPrimary: '#198cb2',
      borderRadius: 8,
      wireframe: false
    }
  }

  // Light theme configuration
  const lightTheme = {
    ...commonTheme
  }

  // Dark theme configuration
  const darkTheme = {
    ...commonTheme,
    algorithm: theme.darkAlgorithm
  }

  // Current theme configuration
  const currentTheme = ref(isDark.value ? darkTheme : lightTheme)

  // Toggle theme
  function toggleTheme() {
    setTheme(!isDark.value)
  }

  // Set theme
  function setTheme(dark) {
    isDark.value = dark
    currentTheme.value = dark ? darkTheme : lightTheme
    localStorage.setItem('theme', dark ? 'dark' : 'light')
    updateDocumentTheme()
  }

  // Update the document theme class
  function updateDocumentTheme() {
    if (isDark.value) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  // Apply the theme on initialization
  updateDocumentTheme()

  return {
    isDark,
    currentTheme,
    toggleTheme,
    setTheme
  }
})
