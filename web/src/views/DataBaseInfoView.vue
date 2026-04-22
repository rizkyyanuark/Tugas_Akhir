<template>
  <div class="database-info-container">
    <FileDetailModal />

    <!-- Search config modal -->
    <SearchConfigModal
      v-model="searchConfigModalVisible"
      :database-id="databaseId"
      @save="handleSearchConfigSave"
    />

    <FileUploadModal
      v-model:visible="addFilesModalVisible"
      :folder-tree="folderTree"
      :current-folder-id="currentFolderId"
      :is-folder-mode="isFolderUploadMode"
      :mode="addFilesMode"
      @success="onFileUploadSuccess"
    />

    <div class="unified-layout">
      <div class="left-panel" :style="{ width: leftPanelWidth + '%' }">
        <KnowledgeBaseCard />
        <!-- Pending file notice bar -->
        <div v-if="!isDify && (pendingParseCount > 0 || pendingIndexCount > 0)" class="info-panel">
          <div class="banner-item" v-if="pendingParseCount > 0" @click="confirmBatchParse">
            <FileText :size="14" />
            <span>{{ pendingParseCount }} files to parse, click to parse</span>
          </div>
          <div class="banner-item" v-if="pendingIndexCount > 0" @click="confirmBatchIndex">
            <Database :size="14" />
            <span>{{ pendingIndexCount }} files to index, click to index</span>
          </div>
        </div>
        <FileTable
          v-if="!isDify"
          :right-panel-visible="state.rightPanelVisible"
          @show-add-files-modal="showAddFilesModal"
          @toggle-right-panel="toggleRightPanel"
        />
      </div>

      <div v-if="!isDify" class="resize-handle" ref="resizeHandle"></div>

      <div
        class="right-panel"
        :style="{
          width: 100 - leftPanelWidth + '%',
          display: isDify || store.state.rightPanelVisible ? 'flex' : 'none'
        }"
      >
        <a-tabs
          v-model:activeKey="activeTab"
          class="knowledge-tabs"
          :tabBarStyle="{ margin: 0, padding: '0 16px' }"
        >
          <template #rightExtra>
            <a-tooltip title="Search Config" placement="bottom">
              <a-button type="text" class="config-btn" @click="openSearchConfigModal">
                <SettingOutlined />
                <span class="config-text">Search Config</span>
              </a-button>
            </a-tooltip>
          </template>
          <a-tab-pane v-if="!isDify && isGraphSupported" key="graph" tab="Knowledge Graph">
            <KnowledgeGraphSection
              :visible="true"
              :active="activeTab === 'graph'"
              @toggle-visible="() => {}"
            />
          </a-tab-pane>
          <a-tab-pane key="query" tab="Query Test">
            <QuerySection ref="querySectionRef" :visible="true" @toggle-visible="() => {}" />
          </a-tab-pane>
          <a-tab-pane v-if="!isDify" key="mindmap" tab="Knowledge Map">
            <MindMapSection v-if="databaseId" :database-id="databaseId" ref="mindmapSectionRef" />
          </a-tab-pane>
          <a-tab-pane
            v-if="!isDify"
            key="evaluation"
            tab="RAG Evaluation"
            :disabled="!isEvaluationSupported"
          >
            <template #tab>
              <span :style="{ color: !isEvaluationSupported ? 'var(--gray-400)' : '' }">
                RAG Evaluation
                <a-tooltip
                  v-if="!isEvaluationSupported"
                  title="Only supports Milvus knowledge bases"
                >
                  <Info :size="14" style="margin-left: 4px; vertical-align: middle" />
                </a-tooltip>
              </span>
            </template>
            <RAGEvaluationTab
              v-if="databaseId && isEvaluationSupported"
              :database-id="databaseId"
              @switch-to-benchmarks="activeTab = 'benchmarks'"
            />
          </a-tab-pane>
          <a-tab-pane
            v-if="!isDify"
            key="benchmarks"
            tab="Evaluation Benchmark"
            :disabled="!isEvaluationSupported"
          >
            <template #tab>
              <span :style="{ color: !isEvaluationSupported ? 'var(--gray-400)' : '' }">
                Evaluation Benchmark
                <a-tooltip
                  v-if="!isEvaluationSupported"
                  title="Only supports Milvus knowledge bases"
                >
                  <Info :size="14" style="margin-left: 4px; vertical-align: middle" />
                </a-tooltip>
              </span>
            </template>
            <div class="benchmark-management-container">
              <div class="benchmark-content">
                <EvaluationBenchmarks
                  v-if="databaseId && isEvaluationSupported"
                  :database-id="databaseId"
                  @benchmark-selected="
                    (benchmark) => {
                      // Handle benchmark selection logic
                      activeTab = 'evaluation'
                    }
                  "
                  @refresh="
                    () => {
                      // Refresh logic
                    }
                  "
                />
              </div>
            </div>
          </a-tab-pane>
        </a-tabs>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useDatabaseStore } from '@/stores/database'
import { useTaskerStore } from '@/stores/tasker'
import { Info, FileText, Database } from 'lucide-vue-next'
import { SettingOutlined } from '@ant-design/icons-vue'
import { Modal } from 'ant-design-vue'
import KnowledgeBaseCard from '@/components/KnowledgeBaseCard.vue'
import FileTable from '@/components/FileTable.vue'
import FileDetailModal from '@/components/FileDetailModal.vue'
import FileUploadModal from '@/components/FileUploadModal.vue'
import KnowledgeGraphSection from '@/components/KnowledgeGraphSection.vue'
import QuerySection from '@/components/QuerySection.vue'
import MindMapSection from '@/components/MindMapSection.vue'
import RAGEvaluationTab from '@/components/RAGEvaluationTab.vue'
import EvaluationBenchmarks from '@/components/EvaluationBenchmarks.vue'
import SearchConfigModal from '@/components/SearchConfigModal.vue'

const route = useRoute()
const store = useDatabaseStore()
const taskerStore = useTaskerStore()

const databaseId = computed(() => store.databaseId)
const database = computed(() => store.database)
const state = computed(() => store.state)
const isDify = computed(() => database.value.kb_type?.toLowerCase() === 'dify')
// Computed: whether knowledge graph is supported
const isGraphSupported = computed(() => {
  const kbType = database.value.kb_type?.toLowerCase()
  return kbType === 'lightrag'
})

// Computed: whether evaluation is supported
const isEvaluationSupported = computed(() => {
  const kbType = database.value.kb_type?.toLowerCase()
  return kbType === 'milvus'
})

// Compute pending parse file count (status: 'uploaded')
const pendingParseCount = computed(() => {
  const files = store.database.files || {}
  return Object.values(files).filter((f) => !f.is_folder && f.status === 'uploaded').length
})

// Compute pending index file count (status: 'parsed' or 'error_indexing')
const pendingIndexCount = computed(() => {
  const files = store.database.files || {}
  const isLightRAG = database.value?.kb_type?.toLowerCase() === 'lightrag'
  return Object.values(files).filter((f) => {
    if (f.is_folder) return false
    if (isLightRAG) {
      return f.status === 'parsed'
    }
    return f.status === 'parsed' || f.status === 'error_indexing'
  }).length
})

// Confirm batch parse
const confirmBatchParse = () => {
  const fileIds = Object.values(store.database.files || {})
    .filter((f) => f.status === 'uploaded')
    .map((f) => f.file_id)

  if (fileIds.length === 0) {
    return
  }

  Modal.confirm({
    title: 'Batch Parse',
    content: `Are you sure you want to parse ${fileIds.length} files?`,
    onOk: () => store.parseFiles(fileIds)
  })
}

// Confirm batch index
const confirmBatchIndex = () => {
  const isLightRAG = database.value?.kb_type?.toLowerCase() === 'lightrag'
  const fileIds = Object.values(store.database.files || {})
    .filter((f) => {
      if (f.is_folder) return false
      if (isLightRAG) return f.status === 'parsed'
      return f.status === 'parsed' || f.status === 'error_indexing'
    })
    .map((f) => f.file_id)

  if (fileIds.length === 0) {
    return
  }

  if (isLightRAG) {
    Modal.confirm({
      title: 'Batch Index',
      content: `Are you sure you want to index ${fileIds.length} files?`,
      onOk: () => store.indexFiles(fileIds)
    })
    return
  }

  // Non-LightRAG: trigger FileTable indexing flow
  // Temporary simple handling: call store.indexFiles directly
  Modal.confirm({
    title: 'Batch Index',
    content: `Are you sure you want to index ${fileIds.length} files?`,
    onOk: () => store.indexFiles(fileIds)
  })
}

// Tab switching logic - smart default
const activeTab = ref('query')

// Mind map section reference
const mindmapSectionRef = ref(null)

// Query section reference
const querySectionRef = ref(null)

const resetGraphStats = () => {
  store.graphStats = {
    total_nodes: 0,
    total_edges: 0,
    displayed_nodes: 0,
    displayed_edges: 0,
    is_truncated: false
  }
}

// LightRAG defaults to the knowledge graph tab
watch(
  () => [databaseId.value, isGraphSupported.value, isEvaluationSupported.value, isDify.value],
  ([newDbId, supported, , difyMode], oldValue = []) => {
    const [oldDbId, previouslySupported] = oldValue

    if (!newDbId) {
      return
    }

    if (difyMode) {
      activeTab.value = 'query'
      return
    }

    if (newDbId && newDbId !== oldDbId) {
      resetGraphStats()
    } else if (!supported && previouslySupported) {
      resetGraphStats()
    }

    if (
      supported &&
      (newDbId !== oldDbId || previouslySupported === false || previouslySupported === undefined)
    ) {
      activeTab.value = 'graph'
      return
    }

    if (!supported && activeTab.value === 'graph') {
      activeTab.value = 'query'
    }

    // If the KB type does not support evaluation and current tab is evaluation-related, switch to query
    if (
      !isEvaluationSupported.value &&
      (activeTab.value === 'evaluation' || activeTab.value === 'benchmarks')
    ) {
      activeTab.value = 'query'
    }
  },
  { immediate: true }
)

// Toggle right panel visibility
const toggleRightPanel = () => {
  store.state.rightPanelVisible = !store.state.rightPanelVisible
}

// Drag to resize (horizontal only)
const leftPanelWidth = ref(50)
const isDragging = ref(false)
const resizeHandle = ref(null)

// Search config modal
const searchConfigModalVisible = ref(false)

const handleSearchConfigSave = () => {
  store.getDatabaseInfo()
}

// Open search config modal
const openSearchConfigModal = () => {
  searchConfigModalVisible.value = true
}

// Add files modal
const addFilesModalVisible = ref(false)
const currentFolderId = ref(null)
const isFolderUploadMode = ref(false)
const addFilesMode = ref('file')

// Mark whether this is the initial load
const isInitialLoad = ref(true)

// Show add files modal
const showAddFilesModal = (options = {}) => {
  const { isFolder = false, mode = 'file' } = options
  isFolderUploadMode.value = isFolder
  addFilesMode.value = mode
  addFilesModalVisible.value = true
  currentFolderId.value = null // Reset
}

// Folder tree passed to FileUploadModal
const folderTree = computed(() => {
  // Reuse FileTable tree-building logic, or get it from store
  // For simplicity, assume store.database.files is flat and rebuild a selection-only tree here
  // Since FileTable is a child component, ideally this logic should live in store/composable
  // FileTable already has buildFileTree; this can be extracted later
  // Quick implementation: build a simplified tree for folder selection only
  const files = store.database.files || {}
  const fileList = Object.values(files)

  // Simplified tree-building logic (folders only)
  const nodeMap = new Map()
  const roots = []

  // 1. Initialize nodes
  fileList.forEach((file) => {
    if (file.is_folder) {
      const item = { ...file, title: file.filename, value: file.file_id, children: [] }
      nodeMap.set(file.file_id, item)
    }
  })

  // 2. Build hierarchy
  fileList.forEach((file) => {
    if (file.is_folder && file.parent_id && nodeMap.has(file.parent_id)) {
      const parent = nodeMap.get(file.parent_id)
      const child = nodeMap.get(file.file_id)
      if (parent && child) {
        parent.children.push(child)
      }
    } else if (file.is_folder && !file.parent_id) {
      // Only explicit root folders are added to roots
      // Folders generated from implicit paths are not selectable in this simplified version
      // because they do not have physical IDs unless we reuse FileTable's full logic
      // If users create folders via the new-folder feature, this logic is sufficient
      if (nodeMap.has(file.file_id)) {
        roots.push(nodeMap.get(file.file_id))
      }
    }
  })

  return roots
})

// File upload success callback
const onFileUploadSuccess = () => {
  taskerStore.loadTasks()
}

// Reset file selection state
const resetFileSelectionState = () => {
  store.selectedRowKeys = []
  store.selectedFile = null
  store.state.fileDetailModalVisible = false
}

watch(
  () => route.params.database_id,
  async (newId) => {
    // Mark as initial load when switching knowledge bases
    isInitialLoad.value = true

    store.databaseId = newId
    resetFileSelectionState()
    resetGraphStats()
    store.stopAutoRefresh()
    await store.getDatabaseInfo(newId, false) // Explicitly load query params on initial load
    store.startAutoRefresh()
  },
  { immediate: true }
)

// Watch file list changes and regenerate sample questions when needed
const previousFileCount = ref(0)

watch(
  () => database.value?.files,
  (newFiles) => {
    if (!newFiles) return

    const newFileCount = Object.keys(newFiles).length
    const oldFileCount = previousFileCount.value

    // On first load, only update count and skip side effects
    if (isInitialLoad.value) {
      previousFileCount.value = newFileCount
      isInitialLoad.value = false
      return
    }

    // If file count changes (increase/decrease), regenerate questions only
    if (newFileCount !== oldFileCount) {
      const changeType = newFileCount > oldFileCount ? 'increased' : 'decreased'
      console.log(
        `File count ${changeType} from ${oldFileCount} to ${newFileCount}, preparing to regenerate questions`
      )

      // Regenerate questions whenever files exist, regardless of prior question state
      if (newFileCount > 0) {
        setTimeout(async () => {
          console.log(
            'File count changed, checking whether question generation is needed, querySectionRef:',
            querySectionRef.value
          )
          if (querySectionRef.value) {
            // Check whether auto-generate questions is enabled
            if (database.value.additional_params?.auto_generate_questions) {
              console.log('Start regenerating questions...')
              await querySectionRef.value.generateSampleQuestions(true)
            } else {
              console.log('Auto-generate questions is disabled, skip generation')
            }
          } else {
            console.warn('querySectionRef is not ready, retry later')
            // If component is not ready yet, wait a bit longer
            setTimeout(async () => {
              if (querySectionRef.value) {
                if (database.value.additional_params?.auto_generate_questions) {
                  console.log('Start generating questions after delay...')
                  await querySectionRef.value.generateSampleQuestions(true)
                } else {
                  console.log('Auto-generate questions is disabled, skip generation')
                }
              }
            }, 2000)
          }
        }, 3000) // Wait 3 seconds for backend processing
      } else {
        // If file count becomes 0, clear question list
        console.log('File count is 0, clearing question list')
        setTimeout(() => {
          if (querySectionRef.value) {
            // Clear question list
            querySectionRef.value.clearQuestions()
          }
        }, 1000)
      }
    }

    previousFileCount.value = newFileCount
  },
  { deep: true }
)

// Handle component mount lifecycle
onMounted(() => {
  store.databaseId = route.params.database_id
  resetFileSelectionState()
  store.getDatabaseInfo()
  store.startAutoRefresh()

  // Add drag event listener (horizontal only)
  if (resizeHandle.value) {
    resizeHandle.value.addEventListener('mousedown', handleMouseDown)
  }
})

// Handle component unmount lifecycle
onUnmounted(() => {
  store.stopAutoRefresh()
  if (resizeHandle.value) {
    resizeHandle.value.removeEventListener('mousedown', handleMouseDown)
  }
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('mouseup', handleMouseUp)
})

// Drag resize handlers
const handleMouseDown = () => {
  isDragging.value = true
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleMouseUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

const handleMouseMove = (e) => {
  if (!isDragging.value) return

  const container = document.querySelector('.unified-layout')
  if (!container) return

  const containerRect = container.getBoundingClientRect()
  const newWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100
  leftPanelWidth.value = Math.max(20, Math.min(80, newWidth))
}

const handleMouseUp = () => {
  isDragging.value = false
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('mouseup', handleMouseUp)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}
</script>

<style lang="less" scoped>
.db-main-container {
  display: flex;
  width: 100%;
}

.ant-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.auto-refresh-control {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 6px;

  span {
    color: var(--gray-700);
    font-weight: 500;
    font-size: 14px;
  }

  .ant-switch {
    &.ant-switch-checked {
      background-color: var(--main-color);
    }
  }
}

/* Unified Layout Styles */
.unified-layout {
  display: flex;
  height: 100vh;
  background-color: var(--gray-0);
  gap: 0;

  .left-panel,
  .right-panel {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 8px;
  }

  .left-panel {
    display: flex;
    flex-shrink: 0;
    flex-grow: 1;
    padding-right: 0;
    flex-direction: column;
    // max-height: calc(100% - 16px);
  }

  .info-panel {
    background: var(--gray-10);
    border-radius: 12px;
    border: 1px solid var(--gray-200);
    display: flex;
    gap: 12px;
    padding: 8px 12px;
    margin-bottom: 8px;
    flex-shrink: 0;

    .banner-item {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      background: var(--color-info-50);
      border-left: 3px solid var(--color-info-500);
      border-radius: 2px;
      font-size: 13px;
      color: var(--color-info-700);
      cursor: pointer;
      transition: all 0.2s;

      &:hover {
        background: var(--color-info-100);
      }

      svg {
        color: var(--color-info-500);
      }
    }
  }

  .right-panel {
    flex-grow: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    padding-left: 0;
  }

  .resize-handle {
    width: 4px;
    cursor: col-resize;
    background-color: var(--gray-200);
    position: relative;
    z-index: 10;
    flex-shrink: 0;
    height: 30px;
    top: 40%;
    margin: 0 2px;
    border-radius: 4px;
  }
}

/* Tab styles */
.knowledge-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-10);
  overflow: hidden;

  :deep(.ant-tabs-content) {
    flex: 1;
    height: 100%;
    overflow: hidden;
  }

  :deep(.ant-tabs-tabpane) {
    height: 100%;
    overflow: hidden;
  }

  :deep(.ant-tabs-nav) {
    margin-bottom: 0;
    // background-color: var(--gray-0);
  }

  :deep(.ant-tabs-extra-content) {
    display: flex;
    align-items: center;
    height: 100%;
  }
}

.config-btn {
  color: var(--gray-600);
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 8px;
  height: 32px;
  border-radius: 6px;
  transition: all 0.2s;

  &:hover {
    color: var(--main-color);
    background-color: var(--gray-100);
  }

  .config-text {
    font-size: 14px;
    margin-left: 4px;
  }
}

/* Table row selection styling */
:deep(.ant-table-tbody > tr.ant-table-row-selected > td) {
  background-color: var(--main-5);
}

:deep(.ant-table-tbody > tr:hover > td) {
  background-color: var(--main-5);
}
</style>

<style lang="less">
/* Global styles as fallback */
.ant-popover .query-params-compact {
  width: 220px;
}

.ant-popover .query-params-compact .params-loading {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 80px;
}

.ant-popover .query-params-compact .params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}

.ant-popover .query-params-compact .param-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.ant-popover .query-params-compact .param-item label {
  font-weight: 500;
  color: var(--gray-700);
  margin-right: 8px;
}

/* Improve panel transitions */
.panel-section {
  display: flex;
  flex-direction: column;
  border-radius: 4px;
  transition: all 0.3s;
  min-height: 0;

  &.collapsed {
    height: 36px;
    flex: none;
  }

  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    border-bottom: 1px solid var(--gray-150);
    background-color: var(--gray-25);

    .header-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .section-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--gray-700);
      margin: 0;
    }

    .panel-actions {
      display: flex;
      gap: 0px;
    }
  }

  .content {
    flex: 1;
    min-height: 0;
  }
}

.query-section,
.graph-section {
  .panel-section();

  .content {
    padding: 8px;
    flex: 1;
    overflow: hidden;
  }
}

// Benchmark management styles
.benchmark-management-container {
  height: 100%;
  background: var(--gray-0);
  display: flex;
  flex-direction: column;
}

.benchmark-content {
  flex: 1;
  overflow: hidden;
  min-height: 0;
  padding: 12px 16px;
}
</style>
