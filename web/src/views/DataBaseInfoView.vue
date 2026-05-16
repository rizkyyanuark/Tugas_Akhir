<template>
  <div class="database-info-container">
    <!-- Search config modal -->
    <SearchConfigModal
      v-model="searchConfigModalVisible"
      :database-id="databaseId"
      @save="handleSearchConfigSave"
    />

    <div class="unified-layout">
      <div class="left-panel" :style="{ width: leftPanelWidth + '%' }">
        <KnowledgeBaseCard />
        <div class="text-only-note">
          Runtime knowledge base is text-query only. Data is retrieved from existing Milvus vectors
          and Neo4j graph data.
        </div>
      </div>

      <div v-if="!isDify" class="resize-handle" ref="resizeHandle"></div>

      <div
        class="right-panel"
        :style="{
          width: 100 - leftPanelWidth + '%',
          display: 'flex'
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
            <QuerySection :visible="true" @toggle-visible="() => {}" />
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
import { SettingOutlined } from '@ant-design/icons-vue'
import KnowledgeBaseCard from '@/components/KnowledgeBaseCard.vue'
import KnowledgeGraphSection from '@/components/KnowledgeGraphSection.vue'
import QuerySection from '@/components/QuerySection.vue'
import SearchConfigModal from '@/components/SearchConfigModal.vue'

const route = useRoute()
const store = useDatabaseStore()

const databaseId = computed(() => store.databaseId)
const database = computed(() => store.database || {})
const isDify = computed(() => database.value.kb_type?.toLowerCase() === 'dify')
// Computed: whether knowledge graph is supported
const isGraphSupported = computed(() => {
  const kbType = database.value.kb_type?.toLowerCase()
  return kbType === 'lightrag'
})

// Tab switching logic - smart default
const activeTab = ref('query')

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
  () => [databaseId.value, isGraphSupported.value, isDify.value],
  ([newDbId, supported, difyMode], oldValue = []) => {
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
  },
  { immediate: true }
)

// Drag to resize (horizontal only)
const leftPanelWidth = ref(34)
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

const resetRuntimeState = () => {
  store.selectedRowKeys = []
  store.selectedFile = null
}

watch(
  () => route.params.database_id,
  async (newId) => {
    store.databaseId = newId
    resetRuntimeState()
    resetGraphStats()
    store.stopAutoRefresh()
    await store.getDatabaseInfo(newId, false) // Explicitly load query params on initial load
    store.startAutoRefresh()
  },
  { immediate: true }
)

// Handle component mount lifecycle
onMounted(() => {
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

  .text-only-note {
    margin-top: 8px;
    padding: 10px 12px;
    border: 1px solid var(--gray-200);
    border-radius: 8px;
    background: var(--gray-25);
    color: var(--gray-700);
    font-size: 13px;
    line-height: 1.5;
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
