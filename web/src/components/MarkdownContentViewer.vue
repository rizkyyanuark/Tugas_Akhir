<template>
  <div class="markdown-content-viewer">
    <div class="viewer-header">
      <h4>File Content</h4>
      <div class="header-controls">
        <div class="header-info">
          <span v-if="mappedChunks.length > 0">Total {{ mappedChunks.length }} chunks</span>
          <span>Total length {{ formatTextLength(mergedContent.length) }}</span>
        </div>
        <button
          class="toggle-btn"
          v-if="mappedChunks.length > 0"
          @click="toggleChunkPanel"
          :title="chunkPanelVisible ? 'Hide chunk list' : 'Show chunk list'"
        >
          <ChevronLeft v-if="chunkPanelVisible" :size="14" />
          <ChevronRight v-else :size="14" />
        </button>
      </div>
    </div>

    <div class="viewer-container">
      <!-- Left: Markdown content -->
      <div class="content-panel">
        <MdPreview
          :modelValue="mergedContent"
          :theme="theme"
          previewTheme="github"
          class="markdown-content"
        />
      </div>

      <!-- Right: Chunk info -->
      <div class="chunk-panel" v-show="chunkPanelVisible">
        <div class="chunk-list">
          <div
            v-for="(chunk, index) in mappedChunks"
            :key="chunk.id"
            class="chunk-item"
            :class="{
              active: activeChunkIndex === index,
              highlighted: highlightedChunkIndex === index
            }"
            @click="handleChunkClick(index)"
            @mouseenter="highlightChunk(index)"
            @mouseleave="unhighlightChunk()"
          >
            <div class="chunk-header">
              <span class="chunk-order">#{{ chunk.chunk_order_index }}</span>
              <span class="chunk-id">{{ chunk.id }}</span>
            </div>
            <div class="chunk-meta">
              <span class="chunk-length">{{ formatTextLength(chunk.content.length) }}</span>
              <span class="chunk-range">{{ chunk.startOffset }}-{{ chunk.endOffset }}</span>
            </div>
            <div class="chunk-preview">{{ getChunkPreview(chunk.content) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Floating tooltip -->
    <div v-if="showTooltip && currentChunk" class="chunk-tooltip" :style="tooltipStyle">
      <div class="tooltip-header">
        <strong>Chunk Info</strong>
      </div>
      <div class="tooltip-content">
        <div class="tooltip-row">
          <span class="label">ID:</span>
          <span class="value">{{ currentChunk.id }}</span>
        </div>
        <div class="tooltip-row">
          <span class="label">Order:</span>
          <span class="value">{{ currentChunk.chunk_order_index }}</span>
        </div>
        <div class="tooltip-row">
          <span class="label">Range:</span>
          <span class="value">{{ currentChunk.startOffset }} - {{ currentChunk.endOffset }}</span>
        </div>
        <div class="tooltip-row">
          <span class="label">Length:</span>
          <span class="value">{{ formatTextLength(currentChunk.content.length) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'
import { mergeChunks, getChunkPreview } from '@/utils/chunkUtils'
import { useThemeStore } from '@/stores/theme'
import { ChevronRight, ChevronLeft } from 'lucide-vue-next'

const props = defineProps({
  chunks: {
    type: Array,
    default: () => []
  },
  content: {
    type: String,
    default: ''
  }
})

// Use theme store
const themeStore = useThemeStore()

// Reactive refs
const showTooltip = ref(false)
const currentChunk = ref(null)
const tooltipStyle = ref({ top: '0px', left: '0px' })
const activeChunkIndex = ref(null)
const highlightedChunkIndex = ref(null)
const chunkPanelVisible = ref(false)

// Theme setting - switch dynamically based on system theme
const theme = computed(() => (themeStore.isDark ? 'dark' : 'light'))

// Merge chunks
const mergeResult = computed(() => mergeChunks(props.chunks))
const mergedContent = computed(() => props.content || mergeResult.value.content)
const mappedChunks = computed(() => mergeResult.value.chunks)

// Format text length
function formatTextLength(length) {
  if (!length && length !== 0) return '0 chars'

  if (length < 1000) {
    return `${length} chars`
  } else {
    return `${(length / 1000).toFixed(1)}k chars`
  }
}

// Highlight chunk
function highlightChunk(index) {
  if (!mappedChunks.value?.[index]) return
  highlightedChunkIndex.value = index
  currentChunk.value = mappedChunks.value[index]
}

function unhighlightChunk() {
  highlightedChunkIndex.value = null
  currentChunk.value = null
}

// Handle chunk click
function handleChunkClick(index) {
  if (!mappedChunks.value?.[index]) return
  activeChunkIndex.value = index
}

// Toggle chunk panel visibility
function toggleChunkPanel() {
  chunkPanelVisible.value = !chunkPanelVisible.value
}

// Handle mouse move for tooltip positioning
function handleMouseMove(event) {
  if (!currentChunk.value) return

  tooltipStyle.value = {
    top: event.clientY + 10 + 'px',
    left: event.clientX + 10 + 'px'
  }
}

// Lifecycle
onMounted(() => {
  document.addEventListener('mousemove', handleMouseMove)
})

onUnmounted(() => {
  document.removeEventListener('mousemove', handleMouseMove)
})
</script>

<style scoped>
.markdown-content-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  overflow: hidden;
}

.viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 16px;
  background: var(--gray-25);
  border-bottom: 1px solid var(--gray-200);
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 16px;
}

.toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  border: none;
  border-radius: 4px;
  width: 24px;
  height: 24px;
  padding: 0;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--gray-700);
}

.toggle-btn:hover {
  background: var(--gray-200);
}

.viewer-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.header-info {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--gray-500);
}

.viewer-container {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.content-panel {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: var(--gray-0);
  border-right: 1px solid var(--gray-200);
  min-height: 0; /* Key: ensure flex items can shrink */
}

.markdown-content {
  min-height: 100%;
  overflow: visible;
}

/* MdPreview style overrides */
.markdown-content :deep(.md-editor) {
  /* height: auto !important; */
  min-height: 100%;
}

.markdown-content :deep(.md-editor-preview) {
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  /* height: auto !important; */
  font-size: small;
  min-height: 100%;
}

.markdown-content :deep(.md-editor-preview-wrapper) {
  padding: 0;
  /* height: auto !important; */
  min-height: 100%;
}

.chunk-panel {
  width: 300px;
  overflow-y: auto;
  background: var(--gray-25);
  padding: 16px;
  min-height: 0; /* Ensure flex item can shrink */
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chunk-item {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  padding: 12px;
  /* cursor: pointer; */
  /* transition: all 0.2s ease; */
  /* user-select: none; */
}

.chunk-item:hover {
  border-color: var(--main-color);
  box-shadow: 0 2px 8px rgba(1, 97, 121, 0.1);
}

/* .chunk-item.active {
  border-color: var(--main-color);
  background: var(--main-50);
  box-shadow: 0 2px 8px rgba(1, 97, 121, 0.2);
} */
/*
.chunk-item.highlighted {
  border-color: var(--color-success-500);
  background: var(--main-50);
} */

.chunk-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.chunk-order {
  font-weight: 600;
  color: var(--main-color);
  font-size: 12px;
}

.chunk-id {
  font-size: 11px;
  color: var(--gray-500);
  font-family: monospace;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--gray-600);
}

.chunk-preview {
  font-size: 11px;
  color: var(--gray-500);
  line-height: 1.4;
  /* max-height: 40px; */
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  line-clamp: 4;
}

.chunk-tooltip {
  position: fixed;
  background: var(--gray-0);
  border: 1px solid var(--gray-300);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  padding: 12px;
  z-index: 1000;
  min-width: 250px;
  max-width: 350px;
  pointer-events: none;
}

.tooltip-header {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--gray-200);
}

.tooltip-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tooltip-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.tooltip-row .label {
  font-weight: 500;
  color: var(--gray-600);
  min-width: 50px;
  flex-shrink: 0;
}

.tooltip-row .value {
  color: var(--gray-1000);
  flex: 1;
  word-break: break-all;
}
</style>
