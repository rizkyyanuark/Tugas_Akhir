<template>
  <div class="home-container">
    <!-- Loading State -->
    <div v-if="isLoading" class="loading-container">
      <a-spin size="large" />
      <p class="loading-text">Connecting to services...</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="error-container">
      <a-result status="error" :title="error.title" :sub-title="error.message">
        <template #extra>
          <a-button type="primary" @click="retryLoad">Retry</a-button>
          <a-button :href="faqUrl" target="_blank" rel="noopener noreferrer">FAQ</a-button>
        </template>
      </a-result>
    </div>

    <!-- Normal Content -->
    <template v-else>
      <!-- Header -->
      <header class="site-header">
        <div class="header-inner">
          <div class="logo">
            <img
              :src="infoStore.organization.logo"
              :alt="displayOrganizationName"
              class="logo-img"
            />
            <span class="logo-text">{{ displayOrganizationName }}</span>
          </div>
          <div class="header-actions">
            <a
              class="header-link"
              href="https://github.com/rizkyyanuark/Tugas_Akhir"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="GitHub Repository"
            >
              <svg height="18" width="18" viewBox="0 0 16 16" fill="currentColor">
                <path
                  fill-rule="evenodd"
                  d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
                />
              </svg>
            </a>
            <UserInfoComponent :show-button="true" />
          </div>
        </div>
      </header>

      <!-- Hero Section -->
      <section class="hero-section">
        <div class="hero-inner">
          <div class="hero-text fade-in">
            <p v-if="typedBadge" class="hero-badge" :class="{ typing: isBadgeTyping }">
              <template v-if="badgeParts.number">
                <span>{{ badgeParts.prefix }}</span>
                <a
                  class="badge-link"
                  :href="upstreamUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span class="badge-number">{{ badgeParts.number }}</span>
                </a>
                <span>{{ badgeParts.suffix }}</span>
              </template>
              <template v-else>{{ typedBadge }}</template>
            </p>
            <h1 class="hero-title fade-in delay-1">{{ productTitle }}</h1>
            <Transition name="subtitle-fade" mode="out-in">
              <p v-if="currentSubtitle" class="hero-subtitle" :key="currentSubtitle">
                {{ currentSubtitle }}
              </p>
            </Transition>
            <p class="hero-description fade-in delay-2">{{ heroDescription }}</p>
            <div class="hero-cta fade-in delay-3">
              <button class="btn-primary" @click="goToChat">Start Exploring</button>
              <a
                class="btn-ghost"
                :href="repoUrl"
                target="_blank"
                rel="noopener noreferrer"
              >View Repository →</a>
            </div>
          </div>

          <div class="hero-graph fade-in delay-2" aria-label="Interactive knowledge graph showing Yunesa system architecture">
            <div class="graph-frame">
              <div class="graph-header">
                <span class="graph-dot"></span>
                <span class="graph-label">Connected Knowledge</span>
              </div>
              <div ref="graphContainerRef" class="graph-canvas" id="knowledge-graph"></div>
              <div class="graph-legend">
                <span
                  class="legend-item"
                  v-for="item in legendItems"
                  :key="item.label"
                >
                  <span class="legend-line" :style="item.lineStyle"></span>
                  {{ item.label }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Proof Section -->
      <section class="proof-section" v-if="featureCards.length">
        <div class="section-inner">
          <div class="proof-grid">
            <div
              class="stat-card"
              v-for="(card, index) in featureCards"
              :key="card.label"
              :style="{ '--stagger': index }"
            >
              <div class="stat-headline">
                <span class="stat-icon" v-if="card.icon">
                  <component :is="card.icon" :size="18" :stroke-width="2" />
                </span>
                <p class="stat-value">{{ card.value }}</p>
              </div>
              <p class="stat-label">{{ card.label }}</p>
              <p class="stat-description" v-if="card.description">{{ card.description }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- Action Section -->
      <section class="action-section" v-if="actionLinks.length">
        <div class="section-inner">
          <div class="action-grid">
            <a
              v-for="action in actionLinks"
              :key="action.name"
              class="action-card"
              :href="action.url"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span class="action-icon" v-if="action.icon">
                <component :is="action.icon" :size="18" :stroke-width="2" />
              </span>
              <div class="action-meta">
                <p class="action-title">{{ action.name }}</p>
                <p class="action-url">{{ action.url }}</p>
              </div>
              <span class="action-arrow">→</span>
            </a>
          </div>
        </div>
      </section>

      <!-- Footer -->
      <footer class="site-footer">
        <div class="footer-inner">
          <p class="copyright">{{ infoStore.footer?.copyright || '© 2026 Yunesa Knowledge Engine' }}</p>
        </div>
      </footer>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useInfoStore } from '@/stores/info'
import { useAgentStore } from '@/stores/agent'
import { useThemeStore } from '@/stores/theme'
import { healthApi } from '@/apis/system_api'
import UserInfoComponent from '@/components/UserInfoComponent.vue'
import { Graph } from '@antv/g6'
import {
  BookText,
  Bug,
  Video,
  Route,
  Github,
  Star,
  CheckCircle2,
  GitCommit,
  ShieldCheck
} from 'lucide-vue-next'

const router = useRouter()
const userStore = useUserStore()
const infoStore = useInfoStore()
const agentStore = useAgentStore()
const themeStore = useThemeStore()

// ─── URLs ────────────────────────────────────────────────────
const repoUrl = 'https://github.com/rizkyyanuark/Tugas_Akhir'
const upstreamUrl = 'https://github.com/xerrors/Yuxi'
const faqUrl = 'https://xerrors.github.io/Yuxi/'

// ─── Computed Display ────────────────────────────────────────
const displayOrganizationName = computed(() => {
  return (infoStore.organization?.name || '').trim() || 'Yunesa'
})

const productTitle = computed(() => {
  return (infoStore.branding?.title || '').trim() || 'Yunesa Knowledge Engine'
})

const heroDescription = computed(() => {
  // Fallback chain: config description → config subtitle → hardcoded default
  const desc = (infoStore.branding?.description || '').trim()
  if (desc) return desc
  const sub = (infoStore.branding?.subtitle || '').trim()
  if (sub) return sub
  return 'Yunesa connects user text queries with a Neo4j knowledge graph and Milvus vector search to enable structured exploration of academic knowledge.'
})

// ─── Graph Data & Legend ─────────────────────────────────────
const graphContainerRef = ref(null)
let graph = null

const graphData = {
  nodes: [
    { id: 'yunesa', data: { label: 'Yunesa', kind: 'core' } },
    { id: 'query', data: { label: 'Query', kind: 'query' } },
    { id: 'neo4j', data: { label: 'Neo4j', kind: 'graph' } },
    { id: 'milvus', data: { label: 'Milvus', kind: 'vector' } },
    { id: 'lecturer', data: { label: 'Lecturer', kind: 'entity' } },
    { id: 'publication', data: { label: 'Publication', kind: 'entity' } },
    { id: 'department', data: { label: 'Department', kind: 'entity' } },
    { id: 'answer', data: { label: 'Answer', kind: 'answer' } },
    { id: 'research', data: { label: 'Research', kind: 'entity' } }
  ],
  edges: [
    { source: 'query', target: 'yunesa' },
    { source: 'yunesa', target: 'neo4j' },
    { source: 'yunesa', target: 'milvus' },
    { source: 'neo4j', target: 'lecturer' },
    { source: 'neo4j', target: 'publication' },
    { source: 'neo4j', target: 'department' },
    { source: 'milvus', target: 'publication' },
    { source: 'milvus', target: 'research' },
    { source: 'yunesa', target: 'answer' },
    { source: 'lecturer', target: 'research' }
  ]
}

const legendItems = [
  { label: 'Core', lineStyle: 'border-bottom: 3px solid currentColor' },
  { label: 'Database', lineStyle: 'border-bottom: 2px dashed currentColor' },
  { label: 'Vector', lineStyle: 'border-bottom: 2px dotted currentColor' },
  { label: 'Entity', lineStyle: 'border-bottom: 1.5px solid currentColor; opacity: 0.5' },
  { label: 'Result', lineStyle: 'border-bottom: 2.5px solid currentColor' }
]

const getGraphColors = (dark) => ({
  coreFill: dark ? '#E0E0E0' : '#1A1A1A',
  coreStroke: dark ? '#E0E0E0' : '#1A1A1A',
  coreLabelFill: dark ? '#1A1A1A' : '#FAFAFA',
  nodeFill: dark ? '#1A1A1A' : '#FFFFFF',
  nodeStroke: dark ? 'rgba(255,255,255,0.22)' : 'rgba(0,0,0,0.2)',
  nodeLabelFill: dark ? '#BBBBBB' : '#333333',
  edgeStroke: dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)',
  answerStroke: dark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.35)',
  haloFill: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.02)'
})

const initGraph = () => {
  if (graph) {
    graph.destroy()
    graph = null
  }
  if (!graphContainerRef.value) return

  const dark = themeStore.isDark
  const c = getGraphColors(dark)

  graph = new Graph({
    container: graphContainerRef.value,
    autoFit: 'view',
    autoResize: true,
    padding: [30, 30, 30, 30],
    animation: false,
    data: graphData,
    layout: {
      type: 'd3-force',
      manyBody: { strength: -260 },
      link: { distance: 100 },
      collide: { radius: 35 },
      x: { strength: 0.06 },
      y: { strength: 0.06 }
    },
    node: {
      type: 'circle',
      style: {
        size: (d) => {
          const kind = d.data?.kind
          if (kind === 'core') return 58
          if (kind === 'entity') return 36
          return 42
        },
        fill: (d) => (d.data?.kind === 'core' ? c.coreFill : c.nodeFill),
        stroke: (d) => {
          const kind = d.data?.kind
          if (kind === 'core') return c.coreStroke
          if (kind === 'answer') return c.answerStroke
          return c.nodeStroke
        },
        lineWidth: (d) => {
          const kind = d.data?.kind
          if (kind === 'core') return 3
          if (kind === 'entity') return 1
          if (kind === 'answer') return 2.5
          return 2
        },
        lineDash: (d) => {
          const kind = d.data?.kind
          if (kind === 'graph') return [6, 4]
          if (kind === 'vector') return [2, 3]
          return undefined
        },
        cursor: 'grab',
        labelText: (d) => d.data?.label || d.id,
        labelFill: (d) => (d.data?.kind === 'core' ? c.coreLabelFill : c.nodeLabelFill),
        labelFontSize: (d) => (d.data?.kind === 'core' ? 13 : 10),
        labelFontFamily: "'Inter', system-ui, sans-serif",
        labelFontWeight: (d) => (d.data?.kind === 'core' ? 700 : 600),
        labelPlacement: 'center',
        halo: true,
        haloFill: c.haloFill,
        haloLineWidth: 12
      }
    },
    edge: {
      type: 'line',
      style: {
        stroke: c.edgeStroke,
        lineWidth: 1
      }
    },
    behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element']
  })

  graph.render()
}

// Watch theme for graph re-init
watch(
  () => themeStore.isDark,
  () => {
    nextTick(() => initGraph())
  }
)

// ─── Loading / Health ────────────────────────────────────────
const isLoading = ref(true)
const error = ref(null)
const typedBadge = ref('')
const isBadgeTyping = ref(false)
let badgeTimer = null
let subtitleTimer = null
let starsFetchController = null

// Fetch star count from upstream Yuxi repo (5.4k stars) for the badge
const GITHUB_REPO_API = 'https://api.github.com/repos/xerrors/Yuxi'
const GITHUB_STARS_TIMEOUT = 3000

const formatStars = (count) => {
  if (!Number.isFinite(count) || count <= 0) {
    return ''
  }
  return `${count}`
}

const subtitleIndex = ref(0)

const subtitleOptions = computed(() => {
  const subtitles = infoStore.branding?.subtitles
  if (Array.isArray(subtitles)) {
    const list = subtitles
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter(Boolean)
    if (list.length) {
      return list
    }
  }

  const fallback = (infoStore.branding?.subtitle || '').trim()
  return fallback ? [fallback] : []
})

const currentSubtitle = computed(() => subtitleOptions.value[subtitleIndex.value] || '')
const badgeParts = computed(() => {
  const text = typedBadge.value || ''
  const match = text.match(/^(.*?)(\d[\d,]*\+?)(\s+GitHub Stars.*)?$/)
  if (!match) {
    return {
      prefix: text,
      number: '',
      suffix: ''
    }
  }

  return {
    prefix: match[1] || '',
    number: match[2] || '',
    suffix: match[3] || ''
  }
})

const stopSubtitleCarousel = () => {
  if (subtitleTimer) {
    clearInterval(subtitleTimer)
    subtitleTimer = null
  }
}

const startSubtitleCarousel = () => {
  stopSubtitleCarousel()
  subtitleIndex.value = 0

  if (subtitleOptions.value.length <= 1) {
    return
  }

  subtitleTimer = setInterval(() => {
    subtitleIndex.value = (subtitleIndex.value + 1) % subtitleOptions.value.length
  }, 2800)
}

const stopStarsFetch = () => {
  if (starsFetchController) {
    starsFetchController.abort()
    starsFetchController = null
  }
}

const fetchGithubStars = async () => {
  stopStarsFetch()
  const controller = new AbortController()
  starsFetchController = controller
  const timer = setTimeout(() => {
    controller.abort()
  }, GITHUB_STARS_TIMEOUT)

  try {
    const response = await fetch(GITHUB_REPO_API, { signal: controller.signal })
    if (!response.ok) {
      return null
    }

    const data = await response.json()
    const stars = Number(data?.stargazers_count)
    return Number.isFinite(stars) && stars > 0 ? stars : null
  } catch {
    return null
  } finally {
    clearTimeout(timer)
    if (starsFetchController === controller) {
      starsFetchController = null
    }
  }
}

const getHeroBadgeText = (starsCount = null) => {
  const realtimeStars = formatStars(starsCount)
  if (realtimeStars) {
    return `Built on Yuxi — ${realtimeStars} GitHub Stars`
  }

  // Fallback: try to extract star count from config features
  const features = Array.isArray(infoStore.features) ? infoStore.features : []
  const starFeature = features.find((item) => {
    if (typeof item === 'string') return /star/i.test(item)
    return /star|github/i.test(item?.label || '') || /stars|github/i.test(item?.icon || '')
  })

  if (!starFeature) return ''

  const starValue =
    typeof starFeature === 'string' ? '' : (starFeature?.value || '').toString().trim()

  return starValue ? `Built on Yuxi — ${starValue} GitHub Stars` : 'Built on Yuxi'
}

const stopBadgeTyping = () => {
  if (badgeTimer) {
    clearInterval(badgeTimer)
    badgeTimer = null
  }
  isBadgeTyping.value = false
}

const startBadgeTyping = (starsCount = null) => {
  stopBadgeTyping()
  const text = getHeroBadgeText(starsCount)
  typedBadge.value = ''

  if (!text) {
    return
  }

  let index = 0
  isBadgeTyping.value = true
  badgeTimer = setInterval(() => {
    index += 1
    typedBadge.value = text.slice(0, index)
    if (index >= text.length) {
      stopBadgeTyping()
    }
  }, 45)
}

const checkHealth = async () => {
  try {
    const response = await healthApi.checkHealth()
    if (response.status !== 'ok') {
      throw new Error('Service Unavailable')
    }
  } catch (e) {
    error.value = {
      title: 'Service Connection Failed',
      message: 'The backend service is not responding, please check if the service is running normally'
    }
    throw e
  }
}

const loadData = async () => {
  isLoading.value = true
  error.value = null

  try {
    // Check health status first
    await checkHealth()
    // Load config after health check passes
    await infoStore.loadInfoConfig()
    startSubtitleCarousel()
    const starsCount = await fetchGithubStars()
    startBadgeTyping(starsCount)
    isLoading.value = false
    await nextTick()
    if (graphContainerRef.value) {
      initGraph()
    }
  } catch (e) {
    console.error('Loading failed:', e)
    stopBadgeTyping()
    stopSubtitleCarousel()
    stopStarsFetch()
    typedBadge.value = ''
    isLoading.value = false
  }
}

const retryLoad = () => {
  loadData()
}

const goToChat = async () => {
  // Check if user is logged in
  if (!userStore.isLoggedIn) {
    // After login, should redirect to home or default agent
    sessionStorage.setItem('redirect', '/')
    router.push('/login')
    return
  }

  // Redirect based on user role
  if (userStore.isAdmin) {
    // Admin user redirects to agent management/chat
    await agentStore.initialize()
    router.push('/agent')
    return
  }

  // Regular user redirects to default agent
  try {
    // Get default agent
    const defaultAgent = agentStore.defaultAgent
    if (defaultAgent?.id) {
      router.push(`/agent/${defaultAgent.id}`)
    } else {
      router.push('/agent')
    }
  } catch (error) {
    console.error('Redirection to agent page failed:', error)
    router.push('/')
  }
}

onMounted(() => {
  loadData()
})

onUnmounted(() => {
  stopBadgeTyping()
  stopSubtitleCarousel()
  stopStarsFetch()
  if (graph) {
    graph.destroy()
    graph = null
  }
})

// ─── Icon Mapping ────────────────────────────────────────────
const iconKey = (value) => (typeof value === 'string' ? value.toLowerCase() : '')

const featureIconMap = {
  stars: Star,
  issues: CheckCircle2,
  resolved: CheckCircle2,
  commits: GitCommit,
  license: ShieldCheck,
  default: Star
}

const actionIconMap = {
  doc: BookText,
  docs: BookText,
  document: BookText,
  issue: Bug,
  bug: Bug,
  roadmap: Route,
  plan: Route,
  demo: Video,
  video: Video,
  github: Github,
  default: Github
}

const featureCards = computed(() => {
  const list = Array.isArray(infoStore.features) ? infoStore.features : []
  return list
    .map((item) => {
      if (typeof item === 'string') {
        return {
          label: item,
          value: '',
          description: '',
          icon: featureIconMap.default
        }
      }

      const key = iconKey(item.icon || item.type)
      return {
        label: item.label || item.name || '',
        value: item.value || '',
        description: item.description || '',
        icon: featureIconMap[key] || featureIconMap.default
      }
    })
    .filter((item) => item.label || item.value || item.description)
})

const actionLinks = computed(() => {
  const actions = infoStore.actions
  if (!Array.isArray(actions)) {
    return []
  }

  return actions
    .map((item) => {
      const key = iconKey(item?.icon || item?.type)
      return {
        name: item?.name || item?.label || '',
        url: item?.url || item?.link || '',
        icon: actionIconMap[key] || actionIconMap.default
      }
    })
    .filter((item) => item.name && item.url)
})
</script>

<style lang="less" scoped>
/* ─── Design Tokens ──────────────────────────────────── */
.home-container {
  --hv-bg: #FAFAFA;
  --hv-surface: #FFFFFF;
  --hv-surface-alt: #F5F5F5;
  --hv-border: rgba(0, 0, 0, 0.08);
  --hv-border-strong: rgba(0, 0, 0, 0.16);
  --hv-text: #0A0A0A;
  --hv-text-2: #555555;
  --hv-text-3: #999999;
  --hv-dot: rgba(0, 0, 0, 0.05);
  --hv-hover: rgba(0, 0, 0, 0.02);
  --hv-btn-bg: #0A0A0A;
  --hv-btn-text: #FAFAFA;
  --hv-btn-hover: #333333;

  :global(.dark) & {
    --hv-bg: #0A0A0A;
    --hv-surface: #111111;
    --hv-surface-alt: #1A1A1A;
    --hv-border: rgba(255, 255, 255, 0.08);
    --hv-border-strong: rgba(255, 255, 255, 0.14);
    --hv-text: #EEEEEE;
    --hv-text-2: #888888;
    --hv-text-3: #555555;
    --hv-dot: rgba(255, 255, 255, 0.035);
    --hv-hover: rgba(255, 255, 255, 0.03);
    --hv-btn-bg: #EEEEEE;
    --hv-btn-text: #0A0A0A;
    --hv-btn-hover: #CCCCCC;
  }
}

/* ─── Base ───────────────────────────────────────────── */
.home-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  color: var(--hv-text);
  background-color: var(--hv-bg);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  position: relative;
  overflow-x: hidden;
}

.home-container::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    radial-gradient(circle, var(--hv-dot) 1px, transparent 1px);
  background-size: 24px 24px;
}

.home-container > * {
  position: relative;
  z-index: 1;
}

/* ─── Loading & Error ────────────────────────────────── */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 1rem;
}

.loading-text {
  color: var(--hv-text-3);
  font-size: 0.85rem;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.02em;
}

.error-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem;
}

/* ─── Header ─────────────────────────────────────────── */
.site-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  background: var(--hv-surface);
  border-bottom: 1px solid var(--hv-border);
}

.header-inner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
  height: 48px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.logo-img {
  height: 1.5rem;
}

.logo-text {
  font-size: 0.9rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--hv-text);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.header-link {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  color: var(--hv-text-2);
  transition: color 0.15s ease;

  &:hover {
    color: var(--hv-text);
  }
}

/* ─── Hero Section ───────────────────────────────────── */
.hero-section {
  flex: 1;
  display: flex;
  align-items: center;
  min-height: 100vh;
  padding: 5rem 2rem 2rem;
}

.hero-inner {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4rem;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.hero-text {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 540px;
}

.hero-badge {
  display: inline-flex;
  width: fit-content;
  padding: 0.3rem 0.6rem;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--hv-text-2);
  background: var(--hv-surface-alt);
  border: 1px solid var(--hv-border);
  margin: 0;
}

.badge-link {
  color: inherit;
  text-decoration: none;
}

.badge-number {
  color: var(--hv-text);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 0.15em;
  text-decoration-thickness: 1px;
  text-decoration-color: var(--hv-text-3);
  transition: text-decoration-color 0.15s ease;
}

.badge-link:hover .badge-number {
  text-decoration-color: var(--hv-text);
}

.hero-badge.typing::after {
  content: '';
  display: inline-block;
  width: 1px;
  height: 1em;
  margin-left: 4px;
  background: var(--hv-text-2);
  vertical-align: -0.1em;
  animation: caretBlink 0.7s steps(1, end) infinite;
}

.hero-title {
  font-size: clamp(2.8rem, 4.5vw, 4rem);
  font-weight: 800;
  margin: 0;
  color: var(--hv-text);
  letter-spacing: -0.04em;
  line-height: 1.05;
}

.hero-subtitle {
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--hv-text-2);
  line-height: 1.4;
  margin: 0;
  min-height: 2em;
}

.subtitle-fade-enter-active,
.subtitle-fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.subtitle-fade-enter-from,
.subtitle-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.hero-description {
  max-width: 480px;
  margin: 0;
  color: var(--hv-text-3);
  font-size: 0.92rem;
  line-height: 1.7;
}

.hero-cta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  margin-top: 0.5rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.6rem 1.6rem;
  font-size: 0.9rem;
  font-weight: 600;
  font-family: 'Inter', system-ui, sans-serif;
  color: var(--hv-btn-text);
  background: var(--hv-btn-bg);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 0.15s ease;
  min-height: 42px;
  letter-spacing: -0.01em;

  &:hover {
    background: var(--hv-btn-hover);
  }

  &:active {
    transform: scale(0.98);
  }
}

.btn-ghost {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--hv-text-2);
  text-decoration: none;
  transition: color 0.15s ease;
  letter-spacing: -0.01em;

  &:hover {
    color: var(--hv-text);
  }
}

/* ─── Graph Frame ────────────────────────────────────── */
.hero-graph {
  width: 100%;
  min-width: 0;
}

.graph-frame {
  width: 100%;
  border: 1px solid var(--hv-border);
  background: var(--hv-surface);
  overflow: hidden;
}

.graph-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--hv-border);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--hv-text-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.graph-dot {
  width: 6px;
  height: 6px;
  background: var(--hv-text-3);
  border-radius: 50%;
}

.graph-canvas {
  width: 100%;
  height: 400px;
  cursor: grab;

  &:active {
    cursor: grabbing;
  }
}

.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.6rem 0.8rem;
  border-top: 1px solid var(--hv-border);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  font-weight: 500;
  color: var(--hv-text-3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.legend-line {
  display: inline-block;
  width: 16px;
  height: 0;
}

/* ─── Section Shared ─────────────────────────────────── */
.section-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
}

/* ─── Proof Section ──────────────────────────────────── */
.proof-section {
  padding: 3rem 0;
  border-top: 1px solid var(--hv-border);
}

.proof-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--hv-border);
  border: 1px solid var(--hv-border);
}

.stat-card {
  padding: 1.2rem 1rem;
  background: var(--hv-surface);
  transition: background 0.15s ease;
  animation: fadeInUp 0.5s ease forwards;
  animation-delay: calc(100ms + var(--stagger) * 80ms);
  opacity: 0;

  &:hover {
    background: var(--hv-hover);
  }
}

.stat-headline {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.stat-icon {
  color: var(--hv-text-3);
}

.stat-value {
  font-size: 1.35rem;
  font-weight: 700;
  margin: 0;
  color: var(--hv-text);
  letter-spacing: -0.02em;
}

.stat-label {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--hv-text-2);
  margin: 0;
}

.stat-description {
  font-size: 0.75rem;
  color: var(--hv-text-3);
  margin: 0.35rem 0 0;
  line-height: 1.4;
}

/* ─── Action Section ─────────────────────────────────── */
.action-section {
  padding: 0 0 3rem;
}

.action-grid {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--hv-border);
  background: var(--hv-surface);
}

.action-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.2rem;
  text-decoration: none;
  color: var(--hv-text);
  transition: background 0.15s ease;
  border-bottom: 1px solid var(--hv-border);

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: var(--hv-hover);
  }
}

.action-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  color: var(--hv-text-3);
  border: 1px solid var(--hv-border);
  flex-shrink: 0;
}

.action-meta {
  flex: 1;
  min-width: 0;
}

.action-title {
  font-size: 0.88rem;
  font-weight: 600;
  margin: 0;
  color: var(--hv-text);
}

.action-url {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: var(--hv-text-3);
  margin: 0.15rem 0 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.action-arrow {
  color: var(--hv-text-3);
  font-size: 0.9rem;
  transition: transform 0.15s ease;
}

.action-card:hover .action-arrow {
  transform: translateX(3px);
}

/* ─── Footer ─────────────────────────────────────────── */
.site-footer {
  border-top: 1px solid var(--hv-border);
  padding: 2rem 0;
}

.footer-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
  text-align: center;
}

.copyright {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: var(--hv-text-3);
  letter-spacing: 0.02em;
  margin: 0;
}

/* ─── Animations ─────────────────────────────────────── */
.fade-in {
  opacity: 0;
  transform: translateY(12px);
  animation: fadeInUp 0.6s ease forwards;
}

.fade-in.delay-1 {
  animation-delay: 80ms;
}

.fade-in.delay-2 {
  animation-delay: 160ms;
}

.fade-in.delay-3 {
  animation-delay: 240ms;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes caretBlink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ─── Responsive ─────────────────────────────────────── */
@media (max-width: 1080px) {
  .hero-inner {
    grid-template-columns: 1fr;
    gap: 2.5rem;
  }

  .hero-text {
    max-width: 100%;
  }

  .hero-graph {
    max-width: 600px;
  }

  .proof-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 720px) {
  .header-inner {
    padding: 0 1rem;
  }

  .hero-section {
    padding: 4.5rem 1rem 2rem;
  }

  .hero-title {
    font-size: 2.5rem;
  }

  .hero-subtitle {
    font-size: 1rem;
  }

  .hero-description {
    font-size: 0.88rem;
  }

  .graph-canvas {
    height: 300px;
  }

  .section-inner {
    padding: 0 1rem;
  }

  .proof-section {
    padding: 2rem 0;
  }

  .proof-grid {
    grid-template-columns: 1fr;
  }

  .graph-legend {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
}

/* ─── Reduced Motion ─────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .fade-in,
  .stat-card {
    animation: none;
    opacity: 1;
    transform: none;
  }

  .hero-badge.typing::after {
    animation: none;
  }
}
</style>
