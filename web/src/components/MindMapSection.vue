<template>
  <div class="mindmap-section">
    <div class="section-content">
      <!-- Loading state -->
      <div v-if="loading" class="loading-state">
        <a-spin size="small" />
        <span>Loading...</span>
      </div>

      <!-- Generating state -->
      <div v-else-if="generating" class="generating-state">
        <a-spin size="small" />
        <span>AI is generating the mind map...</span>
      </div>

      <!-- Empty state -->
      <div v-else-if="!mindmapData" class="empty-state">
        <Network :size="32" />
        <p>No mind map yet</p>
        <a-button type="primary" size="small" @click="generateMindmap">
          <template #icon><Sparkles :size="14" /></template>
          Generate Mind Map
        </a-button>
      </div>

      <!-- Mind map display -->
      <div v-else class="mindmap-container">
        <div class="mindmap-toolbar">
          <a-space :size="8">
            <a-button
              type="text"
              size="small"
              @click="refreshMindmap"
              :loading="generating"
              title="Regenerate"
            >
              <template #icon><RefreshCw :size="14" /></template>
              <span class="toolbar-text">Regenerate</span>
            </a-button>
            <a-button type="text" size="small" @click="fitView" title="Fit View">
              <template #icon><Maximize2 :size="14" /></template>
              <span class="toolbar-text">Fit View</span>
            </a-button>
          </a-space>
        </div>
        <div class="mindmap-svg-container">
          <svg ref="mindmapSvg" class="mindmap-svg"></svg>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import { RefreshCw, Network, Sparkles, Maximize2 } from 'lucide-vue-next'
import { mindmapApi } from '@/apis/mindmap_api'
import { Markmap } from 'markmap-view'
import { Transformer } from 'markmap-lib'

const props = defineProps({
  databaseId: {
    type: String,
    required: true
  }
})

const NOT_FOUND_CN = '\u4e0d\u5b58\u5728'
const NOT_GENERATED_CN = '\u8fd8\u6ca1\u6709\u751f\u6210'

// ============================================================================
// State management
// ============================================================================

const loading = ref(false)
const generating = ref(false)
const mindmapData = ref(null)
const mindmapSvg = ref(null)
let markmapInstance = null

// ============================================================================
// Methods
// ============================================================================

/**
 * Load mind map
 */
const loadMindmap = async () => {
  if (!props.databaseId) return

  try {
    loading.value = true
    const response = await mindmapApi.getByDatabase(props.databaseId)

    if (response.mindmap) {
      mindmapData.value = response.mindmap
      await nextTick()

      // Delay rendering to ensure DOM is fully updated
      setTimeout(() => {
        renderMindmap(response.mindmap)
      }, 100)
    }
  } catch (error) {
    // If it's a 404, it means no mind map has been generated yet; handle silently
    if (
      error?.message?.includes('404') ||
      error?.message?.includes(NOT_FOUND_CN) ||
      error?.message?.includes(NOT_GENERATED_CN)
    ) {
      mindmapData.value = null
    } else {
      console.error('Failed to load mind map:', error)
      const errorMsg = error?.message || String(error)
      message.error('Failed to load mind map: ' + errorMsg)
    }
  } finally {
    loading.value = false
  }
}

/**
 * Generate mind map
 */
const generateMindmap = async () => {
  if (!props.databaseId) return

  try {
    generating.value = true

    const response = await mindmapApi.generateMindmap(
      props.databaseId,
      [], // Use all files
      '' // No custom prompt
    )

    mindmapData.value = response.mindmap

    // Wait for DOM update
    await nextTick()

    // Add a short delay to ensure SVG is fully rendered
    setTimeout(() => {
      renderMindmap(response.mindmap)
      message.success('Mind map generated successfully!')
    }, 100)
  } catch (error) {
    console.error('Failed to generate mind map:', error)
    const errorMsg = error?.message || String(error)
    message.error('Generation failed: ' + errorMsg)
  } finally {
    generating.value = false
  }
}

/**
 * Refresh mind map
 */
const refreshMindmap = async () => {
  await generateMindmap()
}

/**
 * Convert JSON to Markdown
 */
const jsonToMarkdown = (node, level = 0) => {
  if (!node || !node.content) return ''

  const indent = '#'.repeat(level + 1)
  let markdown = `${indent} ${node.content}\n\n`

  if (node.children && node.children.length > 0) {
    for (const child of node.children) {
      markdown += jsonToMarkdown(child, level + 1)
    }
  }

  return markdown
}

/**
 * Render mind map
 */
const renderMindmap = (data, retryCount = 0) => {
  if (!data) return

  if (!mindmapSvg.value) {
    // If SVG ref is not ready, retry up to 3 times
    if (retryCount < 3) {
      setTimeout(() => {
        renderMindmap(data, retryCount + 1)
      }, 100)
      return
    } else {
      console.error('Failed to get SVG container, render aborted')
      message.error('Render failed: SVG container not found')
      return
    }
  }

  try {
    // Clean up previous instance
    if (markmapInstance) {
      markmapInstance.destroy()
    }

    // Convert JSON to Markdown
    const markdown = jsonToMarkdown(data)

    // Transform using Transformer
    const transformer = new Transformer()
    const { root } = transformer.transform(markdown)

    // Create Markmap instance
    markmapInstance = Markmap.create(mindmapSvg.value, {
      duration: 300,
      maxWidth: 200,
      nodeMinHeight: 24,
      paddingX: 8,
      spacingVertical: 5,
      spacingHorizontal: 60
    })

    markmapInstance.setData(root)
    markmapInstance.fit()

    // Fit again after a delay to ensure layout is fully stabilized
    setTimeout(() => {
      if (markmapInstance) {
        markmapInstance.fit()
      }
    }, 300)
  } catch (error) {
    console.error('Failed to render mind map:', error)
    message.error('Render failed: ' + error.message)
  }
}

/**
 * Fit view
 */
const fitView = () => {
  if (markmapInstance) {
    markmapInstance.fit()
  }
}

/**
 * Methods exposed to parent component
 */
defineExpose({
  refreshMindmap,
  generateMindmap
})

// ============================================================================
// Lifecycle
// ============================================================================

// Watch database ID changes
watch(
  () => props.databaseId,
  (newId) => {
    if (newId) {
      loadMindmap()
    }
  },
  { immediate: true }
)

// Observe container resize and fit automatically
let resizeObserver = null

onMounted(() => {
  // Set up ResizeObserver for container size changes
  nextTick(() => {
    if (mindmapSvg.value) {
      const container = mindmapSvg.value.parentElement
      if (container) {
        resizeObserver = new ResizeObserver(() => {
          if (markmapInstance) {
            markmapInstance.fit()
          }
        })
        resizeObserver.observe(container)
      }
    }
  })
})

// Cleanup
onUnmounted(() => {
  if (markmapInstance) {
    markmapInstance.destroy()
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
})
</script>

<style scoped lang="less">
.mindmap-section {
  display: flex;
  flex-direction: column;
  background: var(--gray-0);
  border-top: 1px solid var(--border-color);
  height: 100%;
  min-height: 0;
}

.section-content {
  flex: 1;
  min-height: 200px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.loading-state,
.generating-state,
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
  color: var(--text-secondary);
  font-size: 13px;

  svg {
    color: var(--text-tertiary);
  }

  p {
    margin: 0;
  }
}

.mindmap-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.mindmap-toolbar {
  padding: 8px 16px;
  background: var(--gray-0);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: flex-end;

  .toolbar-text {
    margin-left: 4px;
    font-size: 13px;
  }

  :deep(.ant-btn-text) {
    display: flex;
    align-items: center;

    &:hover {
      background: rgba(0, 0, 0, 0.04);
    }
  }
}

.mindmap-svg-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: var(--gray-0);
}

.mindmap-svg {
  width: 100%;
  height: 100%;
  min-height: 150px;
  display: block;
}

// Ensure parent container has height
:deep(.markmap) {
  width: 100% !important;
  height: 100% !important;
}
</style>
