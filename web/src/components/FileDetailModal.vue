<template>
  <a-modal
    v-model:open="visible"
    width="1200px"
    :footer="null"
    :closable="false"
    wrap-class-name="file-detail"
    @after-open-change="afterOpenChange"
    :bodyStyle="{ height: '80vh', padding: '0' }"
  >
    <template #title>
      <div class="modal-title-wrapper">
        <!-- Left: filename and icon -->
        <div class="file-title">
          <component :is="fileIcon" :style="{ color: fileIconColor, fontSize: '18px' }" />
          <span class="file-name">{{ file?.filename || 'File details' }}</span>
        </div>

        <div class="header-controls">
          <!-- Character / chunk count shown to the left of the segment control -->
          <span class="view-info">
            {{
              viewMode === 'chunks'
                ? chunkCount + ' chunks'
                : formatTextLength(charCount) + ' chars'
            }}
          </span>

          <!-- View mode switch -->
          <div class="view-controls" v-if="file && hasChunks">
            <a-segmented v-model:value="viewMode" :options="viewModeOptions" />
          </div>

          <!-- Download dropdown menu -->
          <a-dropdown trigger="click" v-if="file">
            <a-button type="default" class="download-btn">
              <template #icon><Download :size="16" /></template>
              Download
              <ChevronDown :size="16" style="margin-left: 4px" />
            </a-button>
            <template #overlay>
              <a-menu @click="handleDownloadMenuClick">
                <a-menu-item key="original" :disabled="!file.file_id">
                  <template #icon><Download :size="16" /></template>
                  Download original
                </a-menu-item>
                <a-menu-item
                  key="markdown"
                  :disabled="!((file.lines && file.lines.length > 0) || file.content)"
                >
                  <template #icon><FileText :size="16" /></template>
                  Download Markdown
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>

          <!-- Custom close button -->
          <button class="custom-close-btn" @click="visible = false">
            <X :size="16" />
          </button>
        </div>
      </div>
    </template>
    <div v-if="loading" class="loading-container">
      <a-spin tip="Loading document content..." />
    </div>
    <div v-else-if="file && (hasContent || hasSourcePreview)" class="file-detail-content">
      <div v-if="viewMode === 'source'" class="content-panel source-panel">
        <div v-if="sourcePreviewLoading" class="loading-container">
          <a-spin tip="Loading source file preview..." />
        </div>
        <div
          v-else-if="sourcePreviewUrl && sourcePreviewType === 'image'"
          class="source-preview-wrapper"
        >
          <img
            :src="sourcePreviewUrl"
            :alt="file?.filename || 'Source file preview'"
            class="source-image"
          />
        </div>
        <iframe
          v-else-if="sourcePreviewUrl && sourcePreviewType === 'pdf'"
          :src="sourcePreviewUrl"
          class="source-pdf"
          :title="file?.filename || 'PDF preview'"
        />
        <div v-else class="empty-content">
          <p>No source file preview available</p>
        </div>
      </div>

      <!-- Markdown mode -->
      <div v-else-if="viewMode === 'markdown'" class="content-panel flat-md-preview">
        <MdPreview
          v-if="mergedContent"
          :modelValue="mergedContent"
          :theme="theme"
          previewTheme="github"
          class="markdown-content"
        />
        <div v-else class="empty-content">
          <p>No file content available</p>
        </div>
      </div>

      <!-- Chunks mode: use a grid layout -->
      <div v-else-if="viewMode === 'chunks'" class="chunks-panel">
        <div class="chunk-grid">
          <div v-for="chunk in mappedChunks" :key="chunk.id" class="chunk-card">
            <div class="chunk-card-header">
              <span class="chunk-order">#{{ chunk.chunk_order_index }}</span>
            </div>
            <div class="chunk-card-content">
              {{ chunk.content.replace(/\n+/g, ' ') }}
            </div>
          </div>
        </div>
        <div v-if="mappedChunks.length === 0" class="empty-content">
          <p>No chunk information available</p>
        </div>
      </div>
    </div>

    <div v-else-if="file" class="empty-content">
      <p>No file content available</p>
    </div>
  </a-modal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useDatabaseStore } from '@/stores/database'
import { useThemeStore } from '@/stores/theme'
import { message } from 'ant-design-vue'
import { documentApi } from '@/apis/knowledge_api'
import { mergeChunks } from '@/utils/chunkUtils'
import { getFileIcon, getFileIconColor } from '@/utils/file_utils'
import { getPreviewTypeByPath } from '@/utils/file_preview'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'
import { Download, ChevronDown, FileText, X } from 'lucide-vue-next'

const store = useDatabaseStore()
const themeStore = useThemeStore()

const visible = computed({
  get: () => store.state.fileDetailModalVisible,
  set: (value) => (store.state.fileDetailModalVisible = value)
})

const file = computed(() => store.selectedFile)
const loading = computed(() => store.state.fileDetailLoading)

// File icon
const fileIcon = computed(() => getFileIcon(file.value?.filename))
const fileIconColor = computed(() => getFileIconColor(file.value?.filename))

const downloadingOriginal = ref(false)
const downloadingMarkdown = ref(false)
const sourcePreviewLoading = ref(false)
const sourcePreviewUrl = ref('')

// Theme settings
const theme = computed(() => (themeStore.isDark ? 'dark' : 'light'))

// View mode
const viewMode = ref('markdown')
const hasContent = computed(
  () => (file.value?.lines && file.value?.lines.length > 0) || file.value?.content
)
const sourcePreviewType = computed(() => getPreviewTypeByPath(file.value?.filename || ''))
const hasSourcePreview = computed(() => ['image', 'pdf'].includes(sourcePreviewType.value))
// Whether actual chunk data exists
const hasChunks = computed(() => mappedChunks.value && mappedChunks.value.length > 0)

const viewModeOptions = computed(() => {
  const options = []
  if (hasSourcePreview.value) {
    options.push({ label: 'Source file', value: 'source' })
  }
  options.push({ label: 'Markdown', value: 'markdown' })
  // Show the Chunks option only when actual chunk data exists
  if (hasChunks.value) {
    options.push({ label: 'Chunks', value: 'chunks' })
  }
  return options
})

// Watch file changes; if there are no chunks, reset to markdown
watch(file, (newFile, oldFile) => {
  if (newFile?.file_id !== oldFile?.file_id) {
    revokeSourcePreviewUrl()
  }

  if (!newFile) {
    revokeSourcePreviewUrl()
    return
  }

  if (!hasChunks.value) {
    viewMode.value = hasSourcePreview.value ? 'source' : 'markdown'
  }
})

watch(
  [visible, file],
  async ([open, currentFile]) => {
    if (!open || !currentFile || !hasSourcePreview.value) {
      if (!open || !hasSourcePreview.value) {
        revokeSourcePreviewUrl()
      }
      return
    }

    await loadSourcePreview()
  },
  { immediate: true }
)

// Statistics
const mergeResult = computed(() => mergeChunks(file.value?.lines || []))
const mappedChunks = computed(() => mergeResult.value.chunks)
const mergedContent = computed(() => file.value?.content || mergeResult.value.content || '')
const charCount = computed(() => mergedContent.value.length)
const chunkCount = computed(() => mappedChunks.value.length || file.value?.lines?.length || 0)

// Format text length
function formatTextLength(length) {
  if (!length && length !== 0) return '0 chars'

  if (length < 1000) {
    return `${length}`
  } else {
    return `${(length / 1000).toFixed(1)}k`
  }
}

const afterOpenChange = (open) => {
  if (!open) {
    revokeSourcePreviewUrl()
    store.selectedFile = null
    viewMode.value = 'markdown'
  }
}

const revokeSourcePreviewUrl = () => {
  if (sourcePreviewUrl.value) {
    window.URL.revokeObjectURL(sourcePreviewUrl.value)
    sourcePreviewUrl.value = ''
  }
}

const loadSourcePreview = async () => {
  if (!file.value?.file_id || !store.databaseId || !hasSourcePreview.value) return
  if (sourcePreviewUrl.value) return

  sourcePreviewLoading.value = true
  try {
    const response = await documentApi.downloadDocument(store.databaseId, file.value.file_id)
    const blob = await response.blob()
    revokeSourcePreviewUrl()
    sourcePreviewUrl.value = window.URL.createObjectURL(blob)
  } catch (error) {
    console.error('Failed to load source file preview:', error)
    message.error(error.message || 'Failed to load source file preview')
  } finally {
    sourcePreviewLoading.value = false
  }
}

// Download menu click handler
const handleDownloadMenuClick = ({ key }) => {
  if (key === 'original') {
    handleDownloadOriginal()
  } else if (key === 'markdown') {
    handleDownloadMarkdown()
  }
}

// Download original file
const handleDownloadOriginal = async () => {
  if (!file.value || !file.value.file_id) {
    message.error('File information is incomplete')
    return
  }

  const dbId = store.databaseId
  if (!dbId) {
    message.error('Unable to get the database ID. Please refresh the page and try again.')
    return
  }

  downloadingOriginal.value = true
  try {
    const response = await documentApi.downloadDocument(dbId, file.value.file_id)

    // Get filename
    const contentDisposition = response.headers.get('content-disposition')
    let filename = file.value.filename
    if (contentDisposition) {
      // First try to match RFC 2231 format: filename*=UTF-8''...
      const rfc2231Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/)
      if (rfc2231Match) {
        try {
          filename = decodeURIComponent(rfc2231Match[1])
        } catch (error) {
          console.warn('Failed to decode RFC2231 filename:', rfc2231Match[1], error)
        }
      } else {
        // Fall back to the standard format: filename="..."
        const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1].replace(/['"]/g, '')
          // Decode the URL-encoded filename
          try {
            filename = decodeURIComponent(filename)
          } catch (error) {
            console.warn('Failed to decode filename:', filename, error)
          }
        }
      }
    }

    // Create a blob and download it
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success('Download successful')
  } catch (error) {
    console.error('Error downloading file:', error)
    message.error(error.message || 'File download failed')
  } finally {
    downloadingOriginal.value = false
  }
}

// Download Markdown
const handleDownloadMarkdown = () => {
  const content = mergedContent.value

  if (!content) {
    message.error('No Markdown content available for download')
    return
  }

  downloadingMarkdown.value = true
  try {
    // Generate filename (add .md if the original file does not have it)
    let filename = file.value.filename || 'document.md'
    if (!filename.toLowerCase().endsWith('.md')) {
      // Remove the original extension and append .md
      const lastDotIndex = filename.lastIndexOf('.')
      if (lastDotIndex > 0) {
        filename = filename.substring(0, lastDotIndex) + '.md'
      } else {
        filename = filename + '.md'
      }
    }

    // Create a blob and download it
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success('Download successful')
  } catch (error) {
    console.error('Error downloading Markdown:', error)
    message.error(error.message || 'Markdown download failed')
  } finally {
    downloadingMarkdown.value = false
  }
}
</script>

<style scoped>
.file-detail-content {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.content-panel,
.chunks-panel {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}

.markdown-content {
  min-height: 100%;
}

.source-preview-wrapper {
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: flex-start;
}

.source-image {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 8px;
}

.source-pdf {
  width: 100%;
  max-height: 100%;
  height: calc(100% - 6px);
  border: none;
  border-radius: 8px;
  background: var(--gray-25);
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 200px;
}

.empty-content {
  text-align: center;
  padding: 40px 0;
  color: var(--gray-400);
  width: 100%;
}

/* Chunks panel styles */
.chunk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.chunk-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 12px;
  transition: all 0.2s ease;
}

.chunk-card:hover {
  border-color: var(--main-color);
  box-shadow: 0 2px 8px rgba(1, 97, 121, 0.1);
}

.chunk-card-header {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.chunk-order {
  font-weight: 600;
  color: var(--main-color);
  font-size: 12px;
}

.chunk-card-content {
  font-size: 12px;
  color: var(--gray-600);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
}
</style>

<style lang="less">
.file-detail {
  .ant-modal {
    top: 20px;
  }

  .ant-modal-header {
    .ant-modal-title {
      width: 100%;
    }
  }
}

.modal-title-wrapper {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

/* File title styles */
.file-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--gray-900);
}

.title-info {
  font-size: 13px;
  color: var(--gray-600);
  font-weight: 500;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

/* Download button styles */
.download-btn {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  height: 28px;
  font-size: 13px;
  line-height: 1;
  border-radius: 6px;
  gap: 4px;

  svg {
    vertical-align: middle;
  }
}

/* Custom close button */
.custom-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  color: var(--gray-500);
  transition: all 0.2s;

  &:hover {
    background: var(--gray-100);
    color: var(--gray-700);
  }
}

/* View switch controls */
.view-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.view-info {
  font-size: 12px;
  color: var(--gray-500);
  white-space: nowrap;
}

/* Dropdown menu styles */
.ant-dropdown-menu {
  border-radius: 8px;
  padding: 4px;
}

.ant-dropdown-menu-item {
  border-radius: 6px;
  display: flex;
  align-items: center;
  padding: 8px 12px;

  svg {
    margin-right: 8px;
  }
}
</style>
