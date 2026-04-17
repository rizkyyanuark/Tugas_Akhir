<template>
  <div class="database-empty" v-if="!state.showPage">
    <a-empty>
      <template #description>
        <span>
          Enable the knowledge graph from System Settings in the user menu to start using this page.
        </span>
      </template>
    </a-empty>
  </div>

  <div class="graph-container layout-container" v-else>
    <ViewSwitchHeader
      title="Knowledge Graph"
      :active-key="knowledgeActiveView"
      :items="knowledgeViewItems"
      aria-label="Switch knowledge views"
    >
      <template #actions>
        <div class="db-selector">
          <div class="status-wrapper">
            <div class="status-indicator" :class="graphStatusClass"></div>
            <span class="status-text">{{ graphStatusText }}</span>
          </div>

          <span class="label">Graph Source:</span>
          <a-select
            v-model:value="state.selectedDbId"
            style="width: 240px"
            :options="state.dbOptions"
            @change="handleDbChange"
            :loading="state.loadingDatabases"
            mode="combobox"
            placeholder="Select or enter graph ID"
          />
        </div>

        <a-button v-if="isNeo4j" type="primary" @click="state.showModal = true">
          <UploadOutlined /> Upload File
        </a-button>

        <a-button v-else type="primary" @click="state.showUploadTipModal = true">
          <UploadOutlined /> Upload File
        </a-button>

        <a-button
          v-if="unindexedCount > 0"
          type="primary"
          @click="indexNodes"
          :loading="state.indexing"
        >
          <SyncOutlined v-if="!state.indexing" /> Index {{ unindexedCount }} Nodes
        </a-button>
      </template>
    </ViewSwitchHeader>

    <div class="container-outter">
      <GraphCanvas
        ref="graphRef"
        :graph-data="graph.graphData"
        :graph-info="formattedGraphInfo"
        :highlight-keywords="[state.searchInput]"
        @node-click="graph.handleNodeClick"
        @edge-click="graph.handleEdgeClick"
        @canvas-click="graph.handleCanvasClick"
      >
        <template #top>
          <div class="actions">
            <div class="actions-left">
              <a-input
                v-model:value="state.searchInput"
                placeholder="Search entity (* for all)"
                style="width: 300px"
                @keydown.enter="onSearch"
                allow-clear
              >
                <template #suffix>
                  <component
                    :is="state.searchLoading ? LoadingOutlined : SearchOutlined"
                    @click="onSearch"
                  />
                </template>
              </a-input>

              <a-input
                v-model:value="sampleNodeCount"
                placeholder="Node limit"
                style="width: 120px"
                @keydown.enter="loadSampleNodes"
                :loading="graph.fetching"
              >
                <template #suffix>
                  <component
                    :is="graph.fetching ? LoadingOutlined : ReloadOutlined"
                    @click="loadSampleNodes"
                  />
                </template>
              </a-input>
            </div>

            <div class="actions-right">
              <a-button type="default" @click="exportGraphData" :icon="h(ExportOutlined)">
                Export Data
              </a-button>
            </div>
          </div>
        </template>

        <template #content>
          <a-empty v-show="graph.graphData.nodes.length === 0" style="padding: 4rem 0" />
        </template>
      </GraphCanvas>

      <GraphDetailPanel
        :visible="graph.showDetailDrawer"
        :item="graph.selectedItem"
        :type="graph.selectedItemType"
        :nodes="graph.graphData.nodes"
        @close="graph.handleCanvasClick"
        style="width: 380px"
      />
    </div>

    <a-modal
      :open="state.showModal"
      title="Upload JSONL File"
      @ok="addDocumentByFile"
      @cancel="handleModalCancel"
      ok-text="Add to Graph"
      cancel-text="Cancel"
      :confirm-loading="state.processing"
      :ok-button-props="{ disabled: !hasValidFile }"
    >
      <div class="upload">
        <div class="note">
          <p>Upload a JSONL file to ingest entities and relationships into Neo4j.</p>
        </div>

        <div class="upload-config">
          <div class="config-row">
            <label class="config-label">Embedding model</label>
            <div class="config-field">
              <EmbeddingModelSelector
                v-model:value="state.embedModelName"
                :disabled="!embedModelConfigurable"
                :style="{ width: '100%' }"
              />
            </div>
          </div>

          <div v-if="!embedModelConfigurable" class="config-hint-row">
            Existing graph data already pins the embedding model for this Neo4j database.
          </div>

          <div class="config-row">
            <label class="config-label">Batch size</label>
            <div class="config-field">
              <a-input-number
                v-model:value="state.batchSize"
                :min="1"
                :max="1000"
                style="width: 100%"
              />
            </div>
          </div>

          <div class="config-hint-row">Default: 40, range: 1-1000</div>
        </div>

        <a-upload-dragger
          class="upload-dragger"
          v-model:fileList="fileList"
          name="file"
          :fileList="fileList"
          :max-count="1"
          accept=".jsonl"
          action="/api/knowledge/files/upload?allow_jsonl=true"
          :headers="userStore.getAuthHeaders()"
          @change="handleFileUpload"
          @drop="handleDrop"
        >
          <p class="ant-upload-text">Click or drag a file to this area to upload</p>
          <p class="ant-upload-hint">Only .jsonl files are supported for graph ingestion.</p>
        </a-upload-dragger>
      </div>
    </a-modal>

    <a-modal
      :open="state.showUploadTipModal"
      title="Upload Guidance"
      @cancel="() => (state.showUploadTipModal = false)"
      :footer="null"
      width="520px"
    >
      <div class="upload-tip-content">
        <a-alert
          :message="getUploadTipMessage()"
          type="info"
          show-icon
          style="margin-bottom: 16px"
        />
        <div v-if="!isNeo4j" class="upload-tip-actions">
          <p>
            This source does not support direct file upload from Graph View. Open dashboard or
            knowledge workflows to process documents first.
          </p>
          <div class="action-buttons">
            <a-button type="primary" @click="goToDashboardPage">
              <DatabaseOutlined /> Go to Dashboard
            </a-button>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, h } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useConfigStore } from '@/stores/config'
import {
  UploadOutlined,
  SyncOutlined,
  SearchOutlined,
  ReloadOutlined,
  LoadingOutlined,
  DatabaseOutlined,
  ExportOutlined
} from '@ant-design/icons-vue'
import ViewSwitchHeader from '@/components/ViewSwitchHeader.vue'
import { neo4jApi, unifiedApi } from '@/apis/graph_api'
import { useUserStore } from '@/stores/user'
import GraphCanvas from '@/components/GraphCanvas.vue'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'
import { useGraph } from '@/composables/useGraph'

const configStore = useConfigStore()
const userStore = useUserStore()
const router = useRouter()

const curEmbedModel = computed(() => configStore.config?.embed_model)
const knowledgeActiveView = 'graph'
const knowledgeViewItems = [
  { key: 'graph', label: 'Knowledge Graph', path: '/graph' },
  { key: 'dashboard', label: 'Dashboard', path: '/dashboard' }
]

const graphRef = ref(null)
const graphInfo = ref(null)
const fileList = ref([])
const sampleNodeCount = ref(100)

const graph = reactive(useGraph(graphRef))

const state = reactive({
  loadingGraphInfo: false,
  loadingDatabases: false,
  searchInput: '',
  searchLoading: false,
  showModal: false,
  showUploadTipModal: false,
  processing: false,
  indexing: false,
  showPage: true,
  selectedDbId: 'neo4j',
  dbOptions: [],
  lightragStats: null,
  embedModelName: '',
  batchSize: 40
})

const selectedDbOption = computed(() => {
  return state.dbOptions.find((option) => option.value === state.selectedDbId) || null
})

const isNeo4j = computed(() => {
  return selectedDbOption.value?.type === 'neo4j' || state.selectedDbId === 'neo4j'
})

const modelMatched = computed(() => {
  if (!graphInfo?.value?.embed_model_name) {
    return true
  }
  return graphInfo.value.embed_model_name === curEmbedModel.value
})

const embedModelConfigurable = computed(() => {
  return graphInfo.value?.embed_model_configurable ?? true
})

const hasValidFile = computed(() => {
  return fileList.value.some((file) => file.status === 'done' && file.response?.file_path)
})

const unindexedCount = computed(() => {
  return graphInfo.value?.unindexed_node_count || 0
})

const formattedGraphInfo = computed(() => {
  if (isNeo4j.value) {
    return {
      node_count: graphInfo.value?.entity_count || 0,
      edge_count: graphInfo.value?.relationship_count || 0
    }
  }

  return {
    node_count: state.lightragStats?.total_nodes || 0,
    edge_count: state.lightragStats?.total_edges || 0
  }
})

const loadDatabases = async () => {
  state.loadingDatabases = true
  try {
    const res = await unifiedApi.getGraphs()
    if (res.success && Array.isArray(res.data)) {
      const options = res.data.map((db) => ({
        label: `${db.name} (${db.type})`,
        value: db.id,
        type: db.type
      }))

      if (!options.find((option) => option.value === 'neo4j')) {
        options.unshift({
          label: 'Neo4j (neo4j)',
          value: 'neo4j',
          type: 'neo4j'
        })
      }

      state.dbOptions = options

      if (!state.selectedDbId || !state.dbOptions.find((o) => o.value === state.selectedDbId)) {
        state.selectedDbId = state.dbOptions.length > 0 ? state.dbOptions[0].value : 'neo4j'
      }
      return
    }

    state.dbOptions = [{ label: 'Neo4j (neo4j)', value: 'neo4j', type: 'neo4j' }]
    state.selectedDbId = 'neo4j'
  } catch (error) {
    console.error('Failed to load graph databases:', error)
    state.dbOptions = [{ label: 'Neo4j (neo4j)', value: 'neo4j', type: 'neo4j' }]
    state.selectedDbId = 'neo4j'
  } finally {
    state.loadingDatabases = false
  }
}

const handleDbChange = () => {
  graph.clearGraph()
  state.searchInput = ''
  state.lightragStats = null

  if (isNeo4j.value) {
    loadGraphInfo()
  } else {
    graphInfo.value = null
    loadLightRAGStats()
  }

  loadSampleNodes()
}

const loadLightRAGStats = () => {
  unifiedApi
    .getStats(state.selectedDbId)
    .then((res) => {
      if (res.success) {
        state.lightragStats = res.data
      }
    })
    .catch((error) => {
      console.error('Failed to load graph stats:', error)
    })
}

const loadGraphInfo = () => {
  state.loadingGraphInfo = true

  neo4jApi
    .getInfo()
    .then((data) => {
      graphInfo.value = data.data
      state.embedModelName = graphInfo.value?.embed_model_name || curEmbedModel.value || ''
      state.loadingGraphInfo = false
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to load Neo4j graph info')
      state.loadingGraphInfo = false
    })
}

const addDocumentByFile = () => {
  if (!hasValidFile.value) {
    message.error('Wait until file upload is complete')
    return
  }

  if (!state.embedModelName) {
    message.error('Select an embedding model first')
    return
  }

  state.processing = true

  const uploadedFile = fileList.value.find(
    (file) => file.status === 'done' && file.response?.file_path
  )
  const filePath = uploadedFile?.response?.file_path

  if (!filePath) {
    message.error('Upload response did not include file_path. Please upload again.')
    state.processing = false
    return
  }

  neo4jApi
    .addEntities(filePath, state.selectedDbId || 'neo4j', state.embedModelName, state.batchSize)
    .then((response) => {
      if (response.status === 'success') {
        message.success(response.message || 'File imported into graph database')
        state.showModal = false
        fileList.value = []
        setTimeout(() => {
          loadGraphInfo()
          loadSampleNodes()
        }, 500)
        return
      }

      throw new Error(response.message || 'Failed to add file to graph')
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to import file')
    })
    .finally(() => {
      state.processing = false
    })
}

const loadSampleNodes = () => {
  graph.fetching = true

  unifiedApi
    .getSubgraph({
      db_id: state.selectedDbId,
      node_label: '*',
      max_nodes: Number(sampleNodeCount.value) || 100,
      max_depth: 2
    })
    .then((response) => {
      const result = response.data
      graph.updateGraphData(result?.nodes || [], result?.edges || [])
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to load graph nodes')
    })
    .finally(() => {
      graph.fetching = false
    })
}

const onSearch = () => {
  if (state.searchLoading) {
    message.error('Please wait for the current request to finish')
    return
  }

  state.searchLoading = true

  unifiedApi
    .getSubgraph({
      db_id: state.selectedDbId,
      node_label: state.searchInput || '*',
      max_nodes: Number(sampleNodeCount.value) || 100,
      max_depth: 2
    })
    .then((response) => {
      const result = response.data
      if (!result || !Array.isArray(result.nodes) || !Array.isArray(result.edges)) {
        throw new Error('Invalid graph response format')
      }

      graph.updateGraphData(result.nodes, result.edges)

      if (graph.graphData.nodes.length === 0) {
        message.info('No matching entities found')
      }
    })
    .catch((error) => {
      console.error('Graph query failed:', error)
      message.error(error.message || 'Graph query failed')
    })
    .finally(() => {
      state.searchLoading = false
    })
}

const handleFileUpload = ({ file, fileList: newFileList }) => {
  fileList.value = newFileList

  if (file.status === 'error') {
    message.error(`Upload failed: ${file.name}`)
  }

  if (file.status === 'done' && file.response?.file_path) {
    message.success(`Uploaded: ${file.name}`)
  }
}

const handleDrop = (event) => {
  console.log('File dropped:', event)
}

const handleModalCancel = () => {
  state.showModal = false
  fileList.value = []
}

const graphStatusClass = computed(() => {
  if (state.loadingGraphInfo) {
    return 'loading'
  }
  return graphInfo.value?.status === 'open' ? 'open' : 'closed'
})

const graphStatusText = computed(() => {
  if (state.loadingGraphInfo) {
    return 'Loading'
  }
  return graphInfo.value?.status === 'open' ? 'Connected' : 'Disconnected'
})

const indexNodes = () => {
  if (!modelMatched.value) {
    message.error(
      `Embedding model mismatch: current model is ${curEmbedModel.value}, but graph model is ${graphInfo.value?.embed_model_name}`
    )
    return
  }

  if (state.processing) {
    message.error('Another process is currently running, please try again later')
    return
  }

  state.indexing = true
  neo4jApi
    .indexEntities(state.selectedDbId || 'neo4j')
    .then((response) => {
      message.success(response.message || 'Indexes added successfully')
      loadGraphInfo()
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to add indexes')
    })
    .finally(() => {
      state.indexing = false
    })
}

const exportGraphData = () => {
  const payload = {
    nodes: graph.graphData.nodes,
    edges: graph.graphData.edges,
    graphInfo: isNeo4j.value ? graphInfo.value : state.lightragStats,
    source: state.selectedDbId,
    exportTime: new Date().toISOString()
  }

  const dataBlob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(dataBlob)
  const link = document.createElement('a')
  link.href = url
  link.download = `graph-data-${state.selectedDbId}-${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)

  message.success('Graph data exported')
}

const getUploadTipMessage = () => {
  if (isNeo4j.value) {
    return 'Neo4j supports direct JSONL upload from this page.'
  }

  const dbType = selectedDbOption.value?.type || 'unknown'
  const dbLabel = selectedDbOption.value?.label || state.selectedDbId
  return `Current source is ${dbType.toUpperCase()} (${dbLabel}). Use your document ingestion workflow to build graph data first.`
}

const goToDashboardPage = () => {
  state.showUploadTipModal = false
  router.push('/dashboard')
}

onMounted(async () => {
  await loadDatabases()
  if (isNeo4j.value) {
    loadGraphInfo()
  } else {
    loadLightRAGStats()
  }
  loadSampleNodes()
})
</script>

<style lang="less" scoped>
@graph-header-height: 50px;

.database-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}

.graph-container {
  padding: 0;
  background-color: var(--gray-0);

  .header-container {
    height: @graph-header-height;
  }
}

.db-selector {
  display: flex;
  align-items: center;

  .label {
    font-size: 14px;
    margin-right: 8px;
    color: var(--color-text-secondary);
  }
}

.status-wrapper {
  display: flex;
  align-items: center;
  margin-right: 16px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.status-text {
  margin-left: 8px;
}

.status-indicator {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;

  &.loading {
    background-color: var(--color-warning-500);
    animation: pulse 1.5s infinite ease-in-out;
  }

  &.open {
    background-color: var(--color-success-500);
  }

  &.closed {
    background-color: var(--color-error-500);
  }
}

@keyframes pulse {
  0% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  50% {
    transform: scale(1.2);
    opacity: 1;
  }
  100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
}

.upload {
  margin-bottom: 20px;

  .upload-dragger {
    margin: 0;
  }

  .upload-config {
    margin: 24px 0;
    padding: 16px;
    background-color: var(--gray-0);
    border-radius: 4px;

    .config-row {
      display: flex;
      align-items: center;
      margin-bottom: 16px;

      &:last-of-type {
        margin-bottom: 0;
      }

      .config-label {
        width: 120px;
        flex-shrink: 0;
        font-size: 14px;
        color: var(--color-text);
        text-align: right;
        margin-right: 16px;
      }

      .config-field {
        flex: 1;
        min-width: 0;
      }
    }

    .config-hint-row {
      margin-bottom: 16px;
      padding-left: 136px;
      font-size: 12px;
      color: var(--color-text-secondary);
      line-height: 1.5;

      &:last-child {
        margin-bottom: 0;
      }
    }
  }
}

.container-outter {
  width: 100%;
  height: calc(100vh - @graph-header-height);
  overflow: hidden;
  background: var(--gray-10);

  .actions {
    display: flex;
    justify-content: space-between;
    margin: 20px 0;
    padding: 0 24px;
    width: 100%;
  }
}

.actions {
  top: 0;

  .actions-left,
  .actions-right {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  :deep(.ant-input) {
    padding: 2px 0;
  }

  button {
    height: 37px;
    box-shadow: none;
  }
}

.upload-tip-content {
  .upload-tip-actions {
    p {
      margin-bottom: 16px;
      color: var(--color-text-secondary);
    }
  }

  .action-buttons {
    display: flex;
    justify-content: center;
    margin-top: 20px;
  }
}

@media (max-width: 960px) {
  .db-selector {
    .status-wrapper {
      display: none;
    }

    .label {
      display: none;
    }
  }

  .container-outter .actions {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .actions {
    .actions-left,
    .actions-right {
      width: 100%;
      justify-content: space-between;
      flex-wrap: wrap;
    }
  }
}
</style>
