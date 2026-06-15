<template>
  <div class="kb-result-grouped-list">
    <div v-if="showSummary" class="result-summary">
      Found {{ normalizedChunks.length }} relevant document chunks from
      {{ fileGroupList.length }} files
      <span v-if="hasAcademicEvidence || hasGraphEvidence" class="summary-separator">|</span>
      <span v-if="hasAcademicEvidence || hasGraphEvidence">{{ evidenceSummaryText }}</span>
    </div>

    <div class="kb-results" v-if="normalizedChunks.length > 0">
      <div v-for="fileGroup in fileGroupList" :key="fileGroup.filename" class="file-group">
        <div
          class="file-header"
          :class="{ expanded: expandedFiles.has(fileGroup.filename) }"
          @click="toggleFile(fileGroup.filename)"
        >
          <div class="file-info">
            <FileText :size="14" color="var(--gray-600)" />
            <span class="file-name">{{ fileGroup.filename }}</span>
            <span class="chunk-count">{{ fileGroup.chunks.length }} chunks</span>
          </div>
          <ChevronDown
            :size="14"
            class="expand-icon"
            :class="{ rotated: expandedFiles.has(fileGroup.filename) }"
          />
        </div>

        <div v-if="expandedFiles.has(fileGroup.filename)" class="chunks-container">
          <div
            v-for="(chunk, index) in fileGroup.chunks"
            :key="getChunkKey(chunk, index)"
            class="chunk-item"
            :class="{ 'high-relevance': typeof chunk.score === 'number' && chunk.score > 0.5 }"
            @click="openChunkDetail(chunk, index + 1)"
          >
            <div class="chunk-summary">
              <span class="chunk-index">#{{ index + 1 }}</span>
              <div class="chunk-scores">
                <span v-if="typeof chunk.score === 'number'" class="score-item"
                  >Similarity {{ (chunk.score * 100).toFixed(0) }}%</span
                >
                <span v-if="typeof chunk.rerank_score === 'number'" class="score-item"
                  >Rerank {{ (chunk.rerank_score * 100).toFixed(0) }}%</span
                >
              </div>
              <span class="chunk-preview">{{ getPreviewText(chunk.content) }}</span>
              <Eye :size="14" class="view-icon" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="hasAcademicEvidence || hasGraphEvidence" class="graph-evidence">
      <div class="evidence-header">
        <div class="header-left">
          <Network :size="14" />
          <span>Graph and Academic Evidence</span>
        </div>
        <div v-if="graphCounts.nodes > 0" class="evidence-tabs">
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'visual' }"
            @click="activeTab = 'visual'"
          >
            <Network :size="12" /> Visual Graph
          </button>
          <button
            class="tab-btn"
            :class="{ active: activeTab === 'list' }"
            @click="activeTab = 'list'"
          >
            <List :size="12" /> Triples List
          </button>
        </div>
      </div>
      <div class="evidence-metrics">
        <span v-if="groundingStatus" class="metric-chip">Grounding: {{ groundingStatus }}</span>
        <span v-if="academicStatus && academicStatus !== 'ok'" class="metric-chip"
          >Index status: {{ academicStatus }}</span
        >
        <span v-if="academicCounts.authorPublications" class="metric-chip"
          >Author papers: {{ academicCounts.authorPublications }}</span
        >
        <span v-if="academicCounts.lecturerTopicPublications" class="metric-chip"
          >Lecturer-topic papers: {{ academicCounts.lecturerTopicPublications }}</span
        >
        <span v-if="academicCounts.paperChunks" class="metric-chip"
          >Paper chunks: {{ academicCounts.paperChunks }}</span
        >
        <span v-if="academicCounts.keywords" class="metric-chip"
          >Keywords: {{ academicCounts.keywords }}</span
        >
        <span v-if="academicCounts.entities" class="metric-chip"
          >Entities: {{ academicCounts.entities }}</span
        >
        <span v-if="academicCounts.relationships" class="metric-chip"
          >Relationships: {{ academicCounts.relationships }}</span
        >
        <span v-if="graphCounts.triples" class="metric-chip">Triples: {{ graphCounts.triples }}</span>
      </div>

      <!-- Graph Canvas Visualizer -->
      <div v-show="activeTab === 'visual' && graphCounts.nodes > 0" class="graph-visual-wrapper">
        <GraphCanvas
          ref="graphRef"
          :graph-data="graphController.graphData"
          @node-click="graphController.handleNodeClick"
          @edge-click="graphController.handleEdgeClick"
          @canvas-click="graphController.handleCanvasClick"
        />
        <!-- Floating details card -->
        <GraphDetailPanel
          :visible="graphController.showDetailDrawer"
          :item="graphController.selectedItem"
          :type="graphController.selectedItemType"
          @close="graphController.handleCanvasClick"
        />
      </div>

      <div v-show="activeTab === 'list' || graphCounts.nodes === 0" v-if="graphTriples.length" class="triple-list">
        <div v-for="(triple, index) in graphTriples" :key="getTripleKey(triple, index)" class="triple-item">
          <span class="triple-source">{{ triple.source }}</span>
          <span class="triple-relation">{{ triple.relation }}</span>
          <span class="triple-target">{{ triple.target }}</span>
        </div>
      </div>
    </div>

    <div v-if="fallbackText && !hasAnyStructuredEvidence" class="raw-evidence">
      {{ fallbackText }}
    </div>

    <div v-if="!hasAnyEvidence" class="no-results">
      <p>{{ emptyText }}</p>
    </div>

    <KbChunkDetailModal
      v-model:open="modalVisible"
      :chunk="selectedChunk"
      :title-prefix="`Document Chunk #${selectedChunkIndex || '-'} `"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch, reactive } from 'vue'
import { FileText, ChevronDown, Eye, Network, List } from 'lucide-vue-next'
import KbChunkDetailModal from './KbChunkDetailModal.vue'
import GraphCanvas from '@/components/GraphCanvas.vue'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'
import { useGraph } from '@/composables/useGraph'

const props = defineProps({
  chunks: {
    type: Array,
    default: () => []
  },
  showSummary: {
    type: Boolean,
    default: true
  },
  emptyText: {
    type: String,
    default: 'No relevant knowledge base content found'
  },
  academicRetrieval: {
    type: Object,
    default: () => ({})
  },
  graph: {
    type: Object,
    default: () => ({})
  },
  grounding: {
    type: Object,
    default: () => ({})
  },
  evidenceSummary: {
    type: String,
    default: ''
  },
  rawText: {
    type: String,
    default: ''
  }
})

const graphRef = ref(null)
const graphController = reactive(useGraph(graphRef))
const activeTab = ref('visual')

const computedGraph = computed(() => {
  const hasNodesOrEdges = (props.graph?.nodes?.length > 0) || (props.graph?.edges?.length > 0)
  if (hasNodesOrEdges) {
    return {
      nodes: props.graph.nodes || [],
      edges: props.graph.edges || []
    }
  }

  // Otherwise construct nodes/edges dynamically from triples
  const nodesMap = new Map()
  const edges = []
  let edgeId = 0

  const triples = graphTriples.value
  triples.forEach((triple) => {
    let source = ''
    let relation = ''
    let target = ''
    if (Array.isArray(triple) && triple.length >= 3) {
      [source, relation, target] = triple
    } else if (triple && typeof triple === 'object') {
      source = triple.source
      relation = triple.relation
      target = triple.target
    }

    if (source && typeof source === 'string') {
      const trimmedSource = source.trim()
      if (trimmedSource && !nodesMap.has(trimmedSource)) {
        nodesMap.set(trimmedSource, {
          id: trimmedSource,
          name: trimmedSource
        })
      }
    }

    if (target && typeof target === 'string') {
      const trimmedTarget = target.trim()
      if (trimmedTarget && !nodesMap.has(trimmedTarget)) {
        nodesMap.set(trimmedTarget, {
          id: trimmedTarget,
          name: trimmedTarget
        })
      }
    }

    if (source && target && relation) {
      const trimmedSource = source.trim()
      const trimmedTarget = target.trim()
      const trimmedRelation = String(relation).trim()
      if (trimmedSource && trimmedTarget && trimmedRelation) {
        edges.push({
          source_id: trimmedSource,
          target_id: trimmedTarget,
          type: trimmedRelation,
          id: `edge_${edgeId++}`
        })
      }
    }
  })

  return {
    nodes: Array.from(nodesMap.values()),
    edges: edges
  }
})

watch(
  computedGraph,
  (newGraph) => {
    if (newGraph && (newGraph.nodes?.length > 0 || newGraph.edges?.length > 0)) {
      graphController.updateGraphData(newGraph.nodes, newGraph.edges)
      activeTab.value = 'visual'
    } else {
      graphController.clearGraph()
      activeTab.value = 'list'
    }
  },
  { immediate: true, deep: true }
)

watch(activeTab, async (tab) => {
  if (tab !== 'visual' || graphCounts.value.nodes === 0) return
  await nextTick()
  setTimeout(() => {
    graphRef.value?.resizeAndFit?.()
  }, 150)
})

const expandedFiles = ref(new Set())
const modalVisible = ref(false)
const selectedChunk = ref(null)
const selectedChunkIndex = ref(null)

const normalizedChunks = computed(() =>
  (props.chunks || []).filter((item) => item && typeof item === 'object' && item.content)
)

const fileGroupList = computed(() => {
  const groups = new Map()
  for (const item of normalizedChunks.value) {
    const filename = item?.metadata?.source || item?.source || item?.metadata?.title || 'Unknown Source'
    if (!groups.has(filename)) {
      groups.set(filename, {
        filename,
        chunks: []
      })
    }
    groups.get(filename).chunks.push(item)
  }

  return Array.from(groups.values()).sort((a, b) => a.filename.localeCompare(b.filename))
})

const academicStatus = computed(() => String(props.academicRetrieval?.status || '').trim())
const groundingStatus = computed(() => String(props.grounding?.status || '').trim())

const academicCounts = computed(() => ({
  authorPublications: Array.isArray(props.academicRetrieval?.author_publications)
    ? props.academicRetrieval.author_publications.length
    : 0,
  lecturerTopicPublications: Array.isArray(props.academicRetrieval?.lecturer_topic_publications)
    ? props.academicRetrieval.lecturer_topic_publications.length
    : 0,
  paperChunks: Array.isArray(props.academicRetrieval?.paper_chunks)
    ? props.academicRetrieval.paper_chunks.length
    : 0,
  keywords: Array.isArray(props.academicRetrieval?.keywords) ? props.academicRetrieval.keywords.length : 0,
  entities: Array.isArray(props.academicRetrieval?.entities) ? props.academicRetrieval.entities.length : 0,
  relationships: Array.isArray(props.academicRetrieval?.relationships)
    ? props.academicRetrieval.relationships.length
    : 0
}))

const graphTriples = computed(() =>
  Array.isArray(props.graph?.triples) ? props.graph.triples.filter((item) => item) : []
)

const graphCounts = computed(() => ({
  nodes: computedGraph.value.nodes.length,
  edges: computedGraph.value.edges.length,
  triples: graphTriples.value.length
}))

const hasAcademicEvidence = computed(() =>
  Object.values(academicCounts.value).some((count) => Number(count) > 0)
)

const hasGraphEvidence = computed(() =>
  graphCounts.value.nodes > 0 || graphCounts.value.edges > 0 || graphCounts.value.triples > 0
)

const hasAnyStructuredEvidence = computed(
  () => normalizedChunks.value.length > 0 || hasAcademicEvidence.value || hasGraphEvidence.value
)

const fallbackText = computed(() => {
  const text = String(props.evidenceSummary || props.rawText || '').trim()
  return text.length <= 900 ? text : `${text.slice(0, 900).trim()}...`
})

const hasAnyEvidence = computed(() => hasAnyStructuredEvidence.value || Boolean(fallbackText.value))

const evidenceSummaryText = computed(() => {
  const parts = []
  if (groundingStatus.value) parts.push(`grounding: ${groundingStatus.value}`)
  if (academicCounts.value.authorPublications)
    parts.push(`${academicCounts.value.authorPublications} author papers`)
  if (academicCounts.value.lecturerTopicPublications)
    parts.push(`${academicCounts.value.lecturerTopicPublications} lecturer-topic papers`)
  if (academicCounts.value.paperChunks) parts.push(`${academicCounts.value.paperChunks} academic chunks`)
  if (academicCounts.value.entities) parts.push(`${academicCounts.value.entities} entities`)
  if (academicCounts.value.relationships) parts.push(`${academicCounts.value.relationships} relationships`)
  if (graphCounts.value.triples) parts.push(`${graphCounts.value.triples} graph triples`)
  return parts.join(', ')
})

watch(
  fileGroupList,
  (groups) => {
    // When groups change, only remove invalid expanded items; keep collapsed by default.
    const validFilenames = new Set(groups.map((item) => item.filename))
    expandedFiles.value = new Set(
      [...expandedFiles.value].filter((filename) => validFilenames.has(filename))
    )
  },
  { immediate: true }
)

const toggleFile = (filename) => {
  if (expandedFiles.value.has(filename)) {
    expandedFiles.value.delete(filename)
  } else {
    expandedFiles.value.add(filename)
  }
}

const getChunkKey = (chunk, index) => {
  if (chunk?.metadata?.chunk_id) return `${chunk.metadata.chunk_id}-${index}`
  return `${chunk?.metadata?.source || chunk?.source || chunk?.metadata?.title || 'chunk'}-${index}`
}

const getTripleKey = (triple, index) =>
  `${triple?.source || 'source'}-${triple?.relation || 'rel'}-${triple?.target || 'target'}-${index}`

const getPreviewText = (text = '') => {
  const content = String(text)
  return content.length <= 100 ? content : `${content.substring(0, 100)}...`
}

const openChunkDetail = (chunk, index) => {
  selectedChunk.value = chunk
  selectedChunkIndex.value = index
  modalVisible.value = true
}
</script>

<style scoped lang="less">
.kb-result-grouped-list {
  padding: 4px;
  .result-summary {
    padding: 10px 12px;
    background: var(--gray-25);
    font-size: 12px;
    color: var(--gray-700);
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    margin-bottom: 8px;

    .summary-separator {
      margin: 0 6px;
      color: var(--gray-400);
    }
  }

  .kb-results {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .file-group {
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    background: var(--gray-0);
    overflow: hidden;

    .file-header {
      padding: 8px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      background: var(--gray-10);

      &:hover {
        background: var(--gray-25);
      }

      &.expanded {
        background: var(--gray-25);
        border-bottom: 1px solid var(--gray-100);
      }

      .file-info {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
        min-width: 0;

        .file-name {
          font-size: 13px;
          color: var(--gray-700);
          flex: 1;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .chunk-count {
          font-size: 11px;
          color: var(--gray-700);
          white-space: nowrap;
        }
      }

      .expand-icon {
        color: var(--gray-700);
        transition: transform 0.2s ease;

        &.rotated {
          transform: rotate(180deg);
        }
      }
    }

    .chunk-item {
      padding: 10px 12px;
      border-bottom: 1px solid var(--gray-100);
      cursor: pointer;

      &:last-child {
        border-bottom: none;
      }

      &.high-relevance {
        background: var(--gray-5);
      }

      &:hover {
        background: var(--gray-25);
      }

      .chunk-summary {
        display: flex;
        align-items: center;
        gap: 8px;

        .chunk-index {
          color: var(--gray-700);
          font-size: 11px;
          min-width: 22px;
          text-align: center;
          background: var(--gray-25);
          border-radius: 4px;
          padding: 1px 4px;
        }

        .chunk-scores {
          display: flex;
          gap: 6px;

          .score-item {
            font-size: 11px;
            color: var(--gray-700);
            background: var(--gray-25);
            border: 1px solid var(--gray-100);
            border-radius: 4px;
            padding: 1px 5px;
            white-space: nowrap;
          }
        }

        .chunk-preview {
          flex: 1;
          min-width: 0;
          font-size: 12px;
          color: var(--gray-700);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .view-icon {
          color: var(--gray-700);
          opacity: 0.5;
        }
      }
    }
  }

  .graph-evidence {
    margin-top: 8px;
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    background: var(--gray-0);
    overflow: hidden;

    .evidence-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 8px 12px;
      background: var(--gray-10);
      color: var(--gray-800);
      font-size: 13px;
      font-weight: 500;

      .header-left {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .evidence-tabs {
        display: flex;
        gap: 6px;

        .tab-btn {
          background: transparent;
          border: 1px solid transparent;
          color: var(--gray-600);
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 4px;
          transition: all 0.2s ease;

          &:hover {
            background: var(--gray-50);
            color: var(--gray-800);
          }

          &.active {
            background: var(--main-50);
            color: var(--main-700);
            border-color: var(--main-100);
          }
        }
      }
    }

    .evidence-metrics {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 8px 12px;
      border-top: 1px solid var(--gray-100);

      .metric-chip {
        border: 1px solid var(--gray-150);
        border-radius: 999px;
        padding: 2px 8px;
        color: var(--gray-700);
        background: var(--gray-25);
        font-size: 11px;
      }
    }

    .graph-visual-wrapper {
      position: relative;
      width: 100%;
      height: 350px;
      overflow: hidden;
      border-top: 1px solid var(--gray-100);
      background: var(--gray-25);

      :deep(.detail-card) {
        top: 10px;
        right: 10px;
        width: 240px;
        max-height: calc(100% - 20px);

        .info-card {
          border-radius: 6px;
          border-color: var(--gray-200);
        }
      }
    }

    .triple-list {
      border-top: 1px solid var(--gray-100);
      padding: 6px 12px 10px;
      display: flex;
      flex-direction: column;
      gap: 6px;

      .triple-item {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: 8px;
        align-items: center;
        font-size: 12px;
        color: var(--gray-700);

        .triple-source,
        .triple-target {
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .triple-relation {
          color: var(--color-primary-600);
          background: var(--gray-25);
          border: 1px solid var(--gray-150);
          border-radius: 4px;
          padding: 1px 6px;
          font-size: 11px;
          white-space: nowrap;
        }
      }
    }
  }

  .raw-evidence {
    margin-top: 8px;
    padding: 10px 12px;
    color: var(--gray-700);
    background: var(--gray-25);
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .no-results {
    text-align: center;
    color: var(--gray-700);
    padding: 14px;
    font-size: 12px;
    border: 1px dashed var(--gray-200);
    border-radius: 8px;
  }
}
</style>
