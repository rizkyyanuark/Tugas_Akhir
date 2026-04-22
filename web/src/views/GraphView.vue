<template>
  <div class="database-empty" v-if="!state.showPage">
    <a-empty>
      <template #description>
        <span> Click "System Settings" in the user menu (top-right) to enable Knowledge Graph. </span>
      </template>
    </a-empty>
  </div>
  <div class="graph-container layout-container" v-else>
    <ViewSwitchHeader
      title="Knowledge base"
      :active-key="knowledgeActiveView"
      :items="knowledgeViewItems"
      aria-label="Knowledge base view switch"
    >
      <template #actions>
        <div class="db-selector">
          <div class="status-wrapper">
            <div class="status-indicator" :class="graphStatusClass"></div>
            <span class="status-text">{{ graphStatusText }}</span>
          </div>
          <span class="label">Knowledge Base: </span>
          <a-select
            v-model:value="state.selectedDbId"
            style="width: 200px"
            :options="state.dbOptions"
            @change="handleDbChange"
            :loading="state.loadingDatabases"
            mode="combobox"
            placeholder="Select or enter KB ID"
          />
          <a-button @click="state.showKgBuilder = true" style="margin-left: 8px">
            <template #icon><SettingOutlined /></template>
            Graph Builder
          </a-button>
        </div>
        <a-button
          v-if="unindexedCount > 0"
          type="primary"
          @click="indexNodes"
          :loading="state.indexing"
        >
          <SyncOutlined v-if="!state.indexing" /> Index {{ unindexedCount }} nodes
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
                placeholder="Enter entity to query (* for all)"
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
                placeholder="Query count"
                style="width: 100px"
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

    <!-- KG Builder Drawer -->
    <a-drawer
      v-model:open="state.showKgBuilder"
      title="Knowledge Graph Builder"
      placement="right"
      width="500px"
      :closable="true"
      :destroyOnClose="false"
    >
      <KGBuilder />
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, h } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useConfigStore } from '@/stores/config'
import {
  SyncOutlined,
  SearchOutlined,
  ReloadOutlined,
  LoadingOutlined,
  DatabaseOutlined,
  SettingOutlined
} from '@ant-design/icons-vue'
import ViewSwitchHeader from '@/components/ViewSwitchHeader.vue'
import KGBuilder from '@/components/KGBuilder.vue'
import { neo4jApi, unifiedApi } from '@/apis/graph_api'
import { useUserStore } from '@/stores/user'
import GraphCanvas from '@/components/GraphCanvas.vue'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'
import { useGraph } from '@/composables/useGraph'

const configStore = useConfigStore()
const cur_embed_model = computed(() => configStore.config?.embed_model)
const knowledgeActiveView = 'graph'
const knowledgeViewItems = [
  { key: 'documents', label: 'Knowledge base', path: '/database' },
  { key: 'graph', label: 'Knowledge Graph', path: '/graph' }
]
const modelMatched = computed(
  () =>
    !graphInfo?.value?.embed_model_name ||
    graphInfo.value.embed_model_name === cur_embed_model.value
)

const router = useRouter()
const graphRef = ref(null)
const graphInfo = ref(null)
const sampleNodeCount = ref(100)

const graph = reactive(useGraph(graphRef))

const state = reactive({
  loadingGraphInfo: false,
  loadingDatabases: false,
  searchInput: '',
  searchLoading: false,
  indexing: false,
  showPage: true,
  selectedDbId: 'neo4j',
  dbOptions: [],
  lightragStats: null,
  showKgBuilder: false
})

const isNeo4j = computed(() => {
  return state.selectedDbId === 'neo4j'
})

const embedModelConfigurable = computed(() => {
  return graphInfo.value?.embed_model_configurable ?? true
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
  } else {
    return {
      node_count: state.lightragStats?.total_nodes || 0,
      edge_count: state.lightragStats?.total_edges || 0
    }
  }
})

const loadDatabases = async () => {
  state.loadingDatabases = true
  try {
    const res = await unifiedApi.getGraphs()
    if (res.success && res.data) {
      state.dbOptions = res.data.map((db) => ({
        label: `${db.name} (${db.type})`,
        value: db.id,
        type: db.type
      }))

      if (!state.selectedDbId || !state.dbOptions.find((o) => o.value === state.selectedDbId)) {
        if (state.dbOptions.length > 0) {
          state.selectedDbId = state.dbOptions[0].value
        }
      }
    }
  } catch (error) {
    console.error('Failed to load databases:', error)
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
    .catch((e) => console.error(e))
}

const loadGraphInfo = () => {
  state.loadingGraphInfo = true
  neo4jApi
    .getInfo()
    .then((data) => {
      console.log(data)
      graphInfo.value = data.data
      state.loadingGraphInfo = false
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to load graph info')
      state.loadingGraphInfo = false
    })
}

const loadSampleNodes = () => {
  graph.fetching = true

  unifiedApi
    .getSubgraph({
      db_id: state.selectedDbId,
      node_label: '*',
      max_nodes: sampleNodeCount.value
    })
    .then((data) => {
      const result = data.data
      graph.updateGraphData(result.nodes, result.edges)
      console.log(graph.graphData)
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to load nodes')
    })
    .finally(() => (graph.fetching = false))
}

const onSearch = () => {
  if (state.searchLoading) {
    message.error('Please try again later')
    return
  }

  state.searchLoading = true

  unifiedApi
    .getSubgraph({
      db_id: state.selectedDbId,
      node_label: state.searchInput || '*',
      max_nodes: sampleNodeCount.value
    })
    .then((data) => {
      const result = data.data
      if (!result || !result.nodes || !result.edges) {
        throw new Error('Invalid data format')
      }
      graph.updateGraphData(result.nodes, result.edges)
      if (graph.graphData.nodes.length === 0) {
        message.info('No relevant entities found')
      }
      console.log(data)
      console.log(graph.graphData)
    })
    .catch((error) => {
      console.error('Search error:', error)
      message.error(`Search error: ${error.message || 'Unknown error'}`)
    })
    .finally(() => (state.searchLoading = false))
}

onMounted(async () => {
  await loadDatabases()
  loadGraphInfo()
  loadSampleNodes()
})

const graphStatusClass = computed(() => {
  if (state.loadingGraphInfo) return 'loading'
  return graphInfo.value?.status === 'open' ? 'open' : 'closed'
})

const graphStatusText = computed(() => {
  if (state.loadingGraphInfo) return 'Loading'
  return graphInfo.value?.status === 'open' ? 'Connected' : 'Closed'
})

const indexNodes = () => {
  if (!modelMatched.value) {
    message.error(
      `Model mismatch, cannot index. Current: ${cur_embed_model.value}, Graph: ${graphInfo.value?.embed_model_name}`
    )
    return
  }

  if (state.processing) {
    message.error('Processing in background, please try again later')
    return
  }

  state.indexing = true
  neo4jApi
    .indexEntities('neo4j')
    .then((data) => {
      message.success(data.message || 'Indexing successful')
      loadGraphInfo()
    })
    .catch((error) => {
      console.error(error)
      message.error(error.message || 'Failed to index')
    })
    .finally(() => {
      state.indexing = false
    })
}

const getAuthHeaders = () => {
  const userStore = useUserStore()
  return userStore.getAuthHeaders()
}

</script>

<style lang="less" scoped>
@graph-header-height: 50px;

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
  0% { transform: scale(0.8); opacity: 0.5; }
  50% { transform: scale(1.2); opacity: 1; }
  100% { transform: scale(0.8); opacity: 0.5; }
}

.upload {
  margin-bottom: 20px;
  .upload-dragger { margin: 0px; }
  .upload-config {
    margin: 24px 0;
    padding: 16px;
    background-color: var(--gray-0);
    border-radius: 4px;
    .config-row {
      display: flex;
      align-items: center;
      margin-bottom: 16px;
      &:last-of-type { margin-bottom: 0; }
      .config-label {
        width: 100px;
        flex-shrink: 0;
        font-size: 14px;
        color: var(--color-text);
        text-align: right;
        margin-right: 16px;
      }
      .config-field { flex: 1; min-width: 0; }
    }
    .config-hint-row {
      margin-bottom: 16px;
      padding-left: 116px;
      font-size: 12px;
      color: var(--color-text-secondary);
      line-height: 1.5;
      &:last-child { margin-bottom: 0; }
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
  .tags { display: flex; gap: 8px; }
}

.actions {
  top: 0;
  .actions-left, .actions-right {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  :deep(.ant-input) { padding: 2px 0px; }
  button { height: 37px; box-shadow: none; }
}

.upload-tip-content {
  .upload-tip-actions {
    p { margin-bottom: 16px; color: var(--color-text-secondary); }
  }
  .action-buttons {
    display: flex;
    justify-content: center;
    margin-top: 20px;
  }
}
</style>
