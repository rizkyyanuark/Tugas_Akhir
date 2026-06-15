<template>
  <div class="graph-canvas-container" ref="rootEl">
    <div v-show="graphData.nodes.length > 0" class="graph-canvas" ref="container"></div>
    <div class="slots">
      <div v-if="$slots.top" class="overlay top">
        <slot name="top" />
      </div>
      <div class="canvas-content">
        <slot name="content" />
      </div>
      <!-- Statistical Info Panel -->
      <div class="graph-stats-panel" v-if="graphData.nodes.length > 0">
        <div class="stat-item">
          <span class="stat-label">Nodes</span>
          <span class="stat-value">{{ graphData.nodes.length }}</span>
          <span v-if="graphInfo?.node_count" class="stat-total">/ {{ graphInfo.node_count }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Edges</span>
          <span class="stat-value">{{ graphData.edges.length }}</span>
          <span v-if="graphInfo?.edge_count" class="stat-total">/ {{ graphInfo.edge_count }}</span>
        </div>
      </div>
      <div v-if="$slots.bottom" class="overlay bottom">
        <slot name="bottom" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { Graph } from '@antv/g6'
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  graphData: {
    type: Object,
    required: true,
    default: () => ({ nodes: [], edges: [] })
  },
  graphInfo: {
    type: Object,
    default: () => ({})
  },
  labelField: { type: String, default: 'name' },
  autoFit: { type: Boolean, default: true },
  autoResize: { type: Boolean, default: true },
  layoutOptions: { type: Object, default: () => ({}) },
  nodeStyleOptions: { type: Object, default: () => ({}) },
  edgeStyleOptions: { type: Object, default: () => ({}) },
  enableFocusNeighbor: { type: Boolean, default: true },
  sizeByDegree: { type: Boolean, default: true },
  highlightKeywords: { type: Array, default: () => [] }
})

const emit = defineEmits(['ready', 'data-rendered', 'node-click', 'edge-click', 'canvas-click'])

const container = ref(null)
const rootEl = ref(null)
const themeStore = useThemeStore()
let graphInstance = null
let resizeObserver = null
let renderTimeout = null
let resizeTimer = null
let fitTimer = null
let highlightTimer = null
let isMounted = false
let retryCount = 0
const MAX_RETRIES = 5

const defaultLayout = {
  type: 'd3-force',
  preventOverlap: true,
  alphaDecay: 0.1,
  alphaMin: 0.01,
  velocityDecay: 0.6,
  iterations: 150,
  force: {
    center: { x: 0.5, y: 0.5, strength: 0.1 },
    charge: { strength: -400, distanceMax: 600 },
    link: { distance: 100, strength: 0.8 }
  },
  collide: { radius: 40, strength: 0.8, iterations: 3 }
}

// CSS variable helper
function getCSSVariable(variableName, element = document.documentElement) {
  return getComputedStyle(element).getPropertyValue(variableName).trim()
}

const nodeTypeColors = {
  Publication: '#2563eb',
  Lecturer: '#059669',
  Concept: '#7c3aed',
  Keyword: '#d97706',
  Venue: '#0891b2',
  Year: '#64748b',
  Institution: '#be123c',
  Problem: '#dc2626',
  Task: '#ea580c',
  Method: '#16a34a',
  Model: '#9333ea',
  Dataset: '#0284c7',
  Metric: '#ca8a04',
  Results: '#0d9488',
  Innovation: '#db2777',
  Field: '#4f46e5',
  Entity: '#64748b',
  Node: '#64748b'
}

function getNodeType(original = {}) {
  return (
    original.type ||
    original.properties?.concept_type ||
    original.properties?.node_type ||
    original.labels?.find((label) => !['KGNode', 'Entity'].includes(label)) ||
    original.labels?.[0] ||
    'Node'
  )
}

function getNodeColor(original = {}) {
  const type = getNodeType(original)
  return nodeTypeColors[type] || nodeTypeColors.Node
}

function formatData() {
  const data = props.graphData || { nodes: [], edges: [] }
  const degrees = new Map()
  const getEndpoint = (edge, side) =>
    edge?.[`${side}_id`] ?? edge?.[side] ?? edge?.[`${side}Id`] ?? null

  for (const n of data.nodes || []) {
    if (n?.id === undefined || n?.id === null) continue
    degrees.set(String(n.id), 0)
  }
  for (const e of data.edges || []) {
    const source = getEndpoint(e, 'source')
    const target = getEndpoint(e, 'target')
    if (source === null || target === null) continue
    const s = String(source)
    const t = String(target)
    degrees.set(s, (degrees.get(s) || 0) + 1)
    degrees.set(t, (degrees.get(t) || 0) + 1)
  }

  const nodes = (data.nodes || [])
    .filter((n) => n?.id !== undefined && n?.id !== null)
    .map((n) => ({
      id: String(n.id),
      data: {
        label: n[props.labelField] ?? n.name ?? String(n.id),
        nodeType: getNodeType(n),
        degree: degrees.get(String(n.id)) || 0,
        original: n
      }
    }))
  const nodeIds = new Set(nodes.map((node) => node.id))

  const edges = (data.edges || [])
    .map((e, idx) => {
      const source = getEndpoint(e, 'source')
      const target = getEndpoint(e, 'target')
      if (source === null || target === null) return null
      const sourceId = String(source)
      const targetId = String(target)
      if (!nodeIds.has(sourceId) || !nodeIds.has(targetId)) return null
      return {
        id: e.id ? String(e.id) : `edge-${idx}`,
        source: sourceId,
        target: targetId,
        data: {
          label: e.type ?? e.relation ?? '',
          original: e
        }
      }
    })
    .filter(Boolean)

  return { nodes, edges }
}

function initGraph() {
  if (!container.value || !isMounted) return

  const width = container.value.offsetWidth
  const height = container.value.offsetHeight

  if (width <= 0 || height <= 0) {
    if (retryCount < MAX_RETRIES) {
      retryCount++
      clearTimeout(renderTimeout)
      renderTimeout = setTimeout(initGraph, 200)
    }
    return
  }

  retryCount = 0
  container.value.innerHTML = ''

  if (graphInstance) {
    try {
      graphInstance.destroy()
    } catch {
      // ignore cleanup error
    }
    graphInstance = null
  }

  graphInstance = new Graph({
    container: container.value,
    width,
    height,
    autoFit: props.autoFit,
    autoResize: props.autoResize,
    layout: { ...defaultLayout, ...props.layoutOptions },
    node: {
      type: 'circle',
      style: {
        labelText: (d) => d.data.label,
        fill: (d) => getNodeColor(d.data.original),
        labelFill: getCSSVariable('--gray-700'),
        labelWordWrap: true, // enable label ellipsis
        labelMaxWidth: '300%',
        size: (d) => {
          if (!props.sizeByDegree) return 24
          const deg = d.data.degree || 0
          return Math.min(15 + deg * 5, 50)
        },
        opacity: 0.9,
        stroke: getCSSVariable('--color-bg-container'),
        lineWidth: 1.5,
        shadowColor: getCSSVariable('--gray-400'),
        shadowBlur: 4,
        ...(props.nodeStyleOptions.style || {})
      },
      palette: props.nodeStyleOptions.palette
    },
    edge: {
      type: 'quadratic',
      style: {
        labelText: (d) => d.data.label,
        labelFill: getCSSVariable('--gray-800'),
        labelBackground: true,
        labelBackgroundFill: getCSSVariable('--gray-100'),
        stroke: getCSSVariable('--gray-400'),
        opacity: 0.8,
        lineWidth: 1.2,
        endArrow: true,
        ...(props.edgeStyleOptions.style || {})
      }
    },
    behaviors: [
      'drag-element',
      'zoom-canvas',
      'drag-canvas',
      'hover-activate',
      {
        type: 'click-select',
        degree: 1,
        state: 'selected', // Selected state
        neighborState: 'active', // Adjacent node state
        unselectedState: 'inactive', // Unselected node state
        multiple: true,
        trigger: ['shift'],
        // Keep default selection behavior enabled to avoid custom event conflicts
        disableDefault: false
      }
    ]
  })

  // Bind events
  graphInstance.on('node:click', (evt) => {
    const { target } = evt
    // Get node ID
    const nodeId = target.id
    const nodeData = graphInstance.getNodeData(nodeId)
    emit('node-click', nodeData)
  })

  graphInstance.on('edge:click', (evt) => {
    const { target } = evt
    const edgeId = target.id
    const edgeData = graphInstance.getEdgeData(edgeId)
    emit('edge-click', edgeData)
  })

  graphInstance.on('canvas:click', (evt) => {
    // Trigger only when clicking blank canvas area
    if (!evt.target) {
      emit('canvas-click')
    }
  })

  emit('ready', graphInstance)
}

async function resizeAndFit() {
  await nextTick()
  if (!graphInstance || !container.value || !isMounted) return
  const width = container.value.offsetWidth
  const height = container.value.offsetHeight
  if (width <= 0 || height <= 0) return

  try {
    if (typeof graphInstance.setSize === 'function') {
      graphInstance.setSize(width, height)
    } else if (typeof graphInstance.changeSize === 'function') {
      graphInstance.changeSize(width, height)
    }
  } catch {
    return
  }

  clearTimeout(fitTimer)
  fitTimer = setTimeout(() => {
    if (!graphInstance || !isMounted) return
    try {
      graphInstance.fitView()
    } catch {
      // ignore transient layout state
    }
  }, 120)
}

async function setGraphData() {
  if (!graphInstance) initGraph()
  if (!graphInstance || !isMounted) return
  const data = formatData()

  graphInstance.setData(data)
  await Promise.resolve(graphInstance.render())
  await resizeAndFit()

  clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => {
    if (!graphInstance || !isMounted) return
    applyHighlightKeywords()
    try {
      graphInstance.fitView()
    } catch {
      // ignore transient layout state
    }
    emit('data-rendered')
  }, 900)
}

// Keyword highlighting
function applyHighlightKeywords() {
  if (!graphInstance || !props.highlightKeywords || props.highlightKeywords.length === 0) return

  const { nodes } = graphInstance.getData()
  const updates = {}

  nodes.forEach((node) => {
    const nodeLabel = node.data.label || node.data[props.labelField] || String(node.id)
    const shouldHighlight = props.highlightKeywords.some(
      (keyword) => keyword.trim() !== '' && nodeLabel.toLowerCase().includes(keyword.toLowerCase())
    )

    if (shouldHighlight) {
      updates[node.id] = ['highlighted']
    }
  })

  if (Object.keys(updates).length > 0) {
    graphInstance.setElementState(updates)
    graphInstance.draw()
  }
}

// Clear highlights
function clearHighlights() {
  if (!graphInstance) return

  const { nodes } = graphInstance.getData()
  const updates = {}

  nodes.forEach((node) => {
    updates[node.id] = []
  })

  if (Object.keys(updates).length > 0) {
    graphInstance.setElementState(updates)
    graphInstance.draw()
  }
}

function renderGraph() {
  if (!isMounted) return
  if (!graphInstance) initGraph()
  void setGraphData()
}

function refreshGraph() {
  if (!isMounted) return
  if (graphInstance) {
    try {
      graphInstance.destroy()
    } catch {
      // ignore cleanup error
    }
    graphInstance = null
  }
  if (container.value) container.value.innerHTML = ''
  retryCount = 0
  clearTimeout(renderTimeout)
  renderTimeout = setTimeout(() => {
    renderGraph()
  }, 300)
}

function fitView() {
  if (graphInstance)
    try {
      graphInstance.fitView()
    } catch {
      // ignore
    }
}
function fitCenter() {
  if (graphInstance)
    try {
      graphInstance.fitCenter()
    } catch {
      // ignore
    }
}
function getInstance() {
  return graphInstance
}

async function focusNode(id) {
  if (!graphInstance || !props.enableFocusNeighbor) return
  const { nodes, edges } = graphInstance.getData()
  const nodeIds = nodes.map((n) => n.id)
  const edgeIds = edges.map((e) => e.id)
  const updates = {}
  nodeIds.forEach((nid) => (updates[nid] = ['hidden']))
  edgeIds.forEach((eid) => (updates[eid] = ['hidden']))
  const neighborSet = new Set()
  const related = []
  edges.forEach((e) => {
    if (e.source === id) {
      neighborSet.add(e.target)
      related.push(e.id)
    } else if (e.target === id) {
      neighborSet.add(e.source)
      related.push(e.id)
    }
  })
  updates[id] = ['focus']
  Array.from(neighborSet).forEach((nid) => (updates[nid] = ['focus']))
  related.forEach((eid) => (updates[eid] = ['focus']))
  await graphInstance.setElementState(updates)
  await graphInstance.draw()
}

async function clearFocus() {
  if (!graphInstance) return
  const { nodes, edges } = graphInstance.getData()
  const nodeIds = nodes.map((n) => n.id)
  const edgeIds = edges.map((e) => e.id)
  const updates = {}
  nodeIds.forEach((nid) => (updates[nid] = []))
  edgeIds.forEach((eid) => (updates[eid] = []))
  await graphInstance.setElementState(updates)
  await graphInstance.draw()
}

watch(
  () => props.graphData,
  () => {
    clearTimeout(renderTimeout)
    renderTimeout = setTimeout(() => void setGraphData(), 50)
  },
  { deep: true }
)

// Watch keyword changes
watch(
  () => props.highlightKeywords,
  () => {
    if (graphInstance) {
      clearHighlights()
      setTimeout(() => applyHighlightKeywords(), 50)
    }
  },
  { deep: true }
)

// Watch theme changes and reload graph
watch(
  () => themeStore.isDark,
  () => {
    if (graphInstance) {
      refreshGraph()
    }
  }
)

onMounted(() => {
  isMounted = true
  // Use ResizeObserver to rerender on container resize
  if (window.ResizeObserver) {
    resizeObserver = new ResizeObserver(() => {
      if (!container.value) return
      const width = container.value.offsetWidth
      const height = container.value.offsetHeight
      if (width > 0 && height > 0) {
        if (!graphInstance) {
          renderGraph()
        } else {
          clearTimeout(resizeTimer)
          resizeTimer = setTimeout(() => {
            void resizeAndFit()
          }, 80)
        }
      }
    })
    if (container.value) resizeObserver.observe(container.value)
  }

  clearTimeout(renderTimeout)
  renderTimeout = setTimeout(() => {
    renderGraph()
  }, 300)

  window.addEventListener('resize', resizeAndFit)
})

onUnmounted(() => {
  isMounted = false
  window.removeEventListener('resize', resizeAndFit)
  if (resizeObserver && container.value) resizeObserver.unobserve(container.value)
  clearTimeout(renderTimeout)
  clearTimeout(resizeTimer)
  clearTimeout(fitTimer)
  clearTimeout(highlightTimer)
  try {
    graphInstance?.destroy()
  } catch {
    // ignore cleanup error
  }
  graphInstance = null
})

// Exposed methods
defineExpose({
  refreshGraph,
  fitView,
  fitCenter,
  getInstance,
  focusNode,
  clearFocus,
  setData: setGraphData,
  applyHighlightKeywords,
  clearHighlights,
  resizeAndFit
})
</script>

<style lang="less">
.graph-canvas-container {
  position: relative;
  width: 100%;
  height: 100%;
  // background-color: var(--gray-0);

  .graph-canvas {
    width: 100%;
    height: 100%;
  }

  .graph-stats-panel {
    position: absolute;
    bottom: 20px;
    left: 20px;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 6px 12px;
    background: var(--color-trans-light);
    border: 1px solid var(--color-border-secondary);
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    pointer-events: auto;
    z-index: 10;
    font-size: 13px;
    backdrop-filter: blur(4px);

    .stat-item {
      display: flex;
      align-items: center;
      gap: 4px;

      .stat-label {
        color: var(--color-text-secondary);
        font-weight: 500;
      }

      .stat-value {
        color: var(--color-text);
        font-weight: 600;
      }

      .stat-total {
        color: var(--color-text-quaternary);
        font-size: 11px;
      }
    }
  }

  .slots {
    // Let overlay layer ignore pointer events by default so interactions pass through to canvas
    pointer-events: none;
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    z-index: 999;

    .overlay {
      width: 100%;
      flex-shrink: 0;
      flex-grow: 0;
      pointer-events: auto;

      &.top {
        top: 0;
      }
      &.bottom {
        bottom: 0;
      }
    }
    .canvas-content {
      // Make middle content layer and children fully passthrough
      pointer-events: none;
      flex: 1;
      background: transparent !important;
    }
    .canvas-content * {
      pointer-events: none;
    }
  }
}

/* Pulse animation for highlighted nodes */
@keyframes highlightPulse {
  0% {
    filter: brightness(1);
  }
  50% {
    filter: brightness(1.3) drop-shadow(0 0 8px rgba(255, 0, 0, 0.8));
  }
  100% {
    filter: brightness(1);
  }
}

.highlight-animation {
  animation: highlightPulse 2s infinite ease-in-out;
}
</style>
