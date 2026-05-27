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
      <div
        class="hero-section"
        :style="heroSceneStyle"
        @pointermove="handleHeroPointerMove"
        @pointerleave="resetHeroPointer"
      >
        <div class="glass-header">
          <div class="logo">
            <img
              :src="infoStore.organization.logo"
              :alt="displayOrganizationName"
              class="logo-img"
            />
            <span class="logo-text">{{ displayOrganizationName }}</span>
          </div>
          <div class="header-actions">
            <div class="github-link">
              <a href="https://github.com/rizkyyanuark/Tugas_Akhir" target="_blank">
                <svg height="20" width="20" viewBox="0 0 16 16" version="1.1">
                  <path
                    fill-rule="evenodd"
                    d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
                  ></path>
                </svg>
              </a>
            </div>
            <UserInfoComponent :show-button="true" />
          </div>
        </div>

        <div class="hero-layout">
          <div class="hero-content reveal-up">
            <p v-if="typedBadge" class="hero-badge" :class="{ typing: isBadgeTyping }">
              <template v-if="badgeParts.number">
                <span>{{ badgeParts.prefix }}</span>
                <a
                  class="hero-badge-link"
                  :href="repoUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span class="hero-badge-number">{{ badgeParts.number }}</span>
                </a>
                <span>{{ badgeParts.suffix }}</span>
              </template>
              <template v-else>{{ typedBadge }}</template>
            </p>
            <h1 class="title reveal-up delay-1">{{ productTitle }}</h1>
            <Transition name="subtitle-switch" mode="out-in">
              <p v-if="currentSubtitle" class="subtitle" :key="currentSubtitle">
                {{ currentSubtitle }}
              </p>
            </Transition>
            <p class="hero-summary">
              YUnesa menghubungkan query teks pengguna dengan knowledge graph Neo4j dan vector
              search Milvus untuk membantu eksplorasi pengetahuan akademik secara terarah.
            </p>
            <div class="hero-actions">
              <button class="button-base primary" @click="goToChat">Mulai Bertanya</button>
              <a class="doc-text-link" href="https://github.com/rizkyyanuark/Tugas_Akhir" target="_blank"
                >Lihat Repository</a
              >
            </div>
          </div>
          <div class="graph-stage reveal-up delay-2" aria-label="YUnesa connected knowledge graph">
            <div class="graph-stage-header">
              <span class="stage-dot"></span>
              <span>Connected Knowledge</span>
            </div>
            <div class="globe-shell">
              <div class="globe-grid" aria-hidden="true">
                <span class="globe-ring ring-main"></span>
                <span class="globe-ring ring-tilt-a"></span>
                <span class="globe-ring ring-tilt-b"></span>
                <span class="globe-ring ring-flat-a"></span>
                <span class="globe-ring ring-flat-b"></span>
              </div>
              <svg class="graph-links" viewBox="0 0 520 520" aria-hidden="true">
                <path
                  v-for="(link, index) in graphLinks"
                  :key="index"
                  :d="link"
                  :style="{ '--link-delay': `${index * 120}ms` }"
                />
              </svg>
              <div
                v-for="node in graphNodes"
                :key="node.label"
                class="knowledge-node"
                :class="node.kind"
                :style="{ left: node.x, top: node.y, '--node-delay': node.delay }"
                :title="node.label"
              >
                <span class="node-pulse"></span>
                <span class="node-label">{{ node.label }}</span>
              </div>
              <div class="globe-core">
                <span>YUnesa</span>
              </div>
            </div>
            <div class="flow-legend">
              <span>Text Query</span>
              <span>Milvus Vector</span>
              <span>Neo4j Graph</span>
              <span>Grounded Answer</span>
            </div>
          </div>
        </div>
      </div>

      <div class="section proof-section" v-if="featureCards.length">
        <div class="proof-grid">
          <div
            class="stat-card"
            v-for="(card, index) in featureCards"
            :key="card.label"
            :style="{ '--card-stagger': `${index}` }"
          >
            <div class="stat-headline">
              <span class="stat-icon" v-if="card.icon">
                <component :is="card.icon" />
              </span>
              <p class="stat-value">{{ card.value }}</p>
            </div>
            <p class="stat-label">{{ card.label }}</p>
            <p class="stat-description">{{ card.description }}</p>
          </div>
        </div>
      </div>

      <div class="section action-section" v-if="actionLinks.length">
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
              <component :is="action.icon" />
            </span>
            <div class="action-meta">
              <p class="action-title">{{ action.name }}</p>
              <p class="action-url">{{ action.url }}</p>
            </div>
          </a>
        </div>
      </div>

      <footer class="footer">
        <div class="footer-content">
          <p class="copyright">{{ infoStore.footer?.copyright || '(C) 2026 YUnesa Knowledge Engine' }}</p>
        </div>
      </footer>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useInfoStore } from '@/stores/info'
import { useAgentStore } from '@/stores/agent'
import { healthApi } from '@/apis/system_api'
import UserInfoComponent from '@/components/UserInfoComponent.vue'
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
const repoUrl = 'https://github.com/rizkyyanuark/Tugas_Akhir'
const faqUrl = 'https://github.com/rizkyyanuark/Tugas_Akhir'

const displayOrganizationName = computed(() => {
  const name = (infoStore.organization?.name || '').trim()
  return /informatics department/i.test(name) ? 'YUnesa' : name || 'YUnesa'
})

const productTitle = computed(() => {
  const title = (infoStore.branding?.title || '').trim()
  return /informatics/i.test(title) || !title ? 'YUnesa Knowledge Engine' : title
})

const graphLinks = [
  'M260 260 C190 190 155 144 104 120',
  'M260 260 C330 180 372 146 424 126',
  'M260 260 C176 270 128 300 84 356',
  'M260 260 C344 276 396 314 446 382',
  'M104 120 C188 96 320 94 424 126',
  'M84 356 C206 430 322 428 446 382',
  'M154 204 C216 154 308 150 372 206',
  'M154 318 C228 364 310 364 372 318',
  'M260 260 C254 176 252 110 260 74',
  'M260 260 C266 342 268 404 260 452'
]

const graphNodes = [
  { label: 'Query', x: '49%', y: '12%', kind: 'query', delay: '0ms' },
  { label: 'Neo4j', x: '18%', y: '23%', kind: 'graph', delay: '120ms' },
  { label: 'Milvus', x: '74%', y: '24%', kind: 'vector', delay: '240ms' },
  { label: 'Dosen', x: '28%', y: '51%', kind: 'entity', delay: '360ms' },
  { label: 'Publikasi', x: '68%', y: '52%', kind: 'entity', delay: '480ms' },
  { label: 'Prodi', x: '16%', y: '72%', kind: 'entity', delay: '600ms' },
  { label: 'Jawaban', x: '74%', y: '76%', kind: 'answer', delay: '720ms' },
  { label: 'Riset', x: '49%', y: '84%', kind: 'entity', delay: '840ms' }
]

const heroPointer = ref({ x: 0, y: 0 })

const heroSceneStyle = computed(() => ({
  '--tilt-x': `${heroPointer.value.y * -7}deg`,
  '--tilt-y': `${heroPointer.value.x * 9}deg`,
  '--cursor-x': `${50 + heroPointer.value.x * 12}%`,
  '--cursor-y': `${50 + heroPointer.value.y * 10}%`
}))

const handleHeroPointerMove = (event) => {
  const rect = event.currentTarget.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2
  const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2
  heroPointer.value = {
    x: Math.max(-1, Math.min(1, x)),
    y: Math.max(-1, Math.min(1, y))
  }
}

const resetHeroPointer = () => {
  heroPointer.value = { x: 0, y: 0 }
}

// Loading state
const isLoading = ref(true)
const error = ref(null)
const typedBadge = ref('')
const isBadgeTyping = ref(false)
let badgeTimer = null
let subtitleTimer = null
let starsFetchController = null

const GITHUB_REPO_API = 'https://api.github.com/repos/rizkyyanuark/Tugas_Akhir'
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
    return `Already has ${realtimeStars} GitHub Stars`
  }

  const features = Array.isArray(infoStore.features) ? infoStore.features : []
  const starFeature = features.find((item) => {
    if (typeof item === 'string') {
      return /star/i.test(item)
    }

    return /star|github/i.test(item?.label || '') || /stars|github/i.test(item?.icon || '')
  })

  if (!starFeature) {
    return ''
  }

  const starValue =
    typeof starFeature === 'string' ? '' : (starFeature?.value || '').toString().trim()

  return starValue ? `Already has ${starValue} GitHub Stars` : 'GitHub Stars reached'
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
  } catch (e) {
    console.error('Loading failed:', e)
    stopBadgeTyping()
    stopSubtitleCarousel()
    stopStarsFetch()
    typedBadge.value = ''
  } finally {
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
  // Load data
  loadData()
})

onUnmounted(() => {
  stopBadgeTyping()
  stopSubtitleCarousel()
  stopStarsFetch()
})

const iconKey = (value) => (typeof value === 'string' ? value.toLowerCase() : '')

// region icon_mapping
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
// endregion icon_mapping

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
.home-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  color: var(--main-900);
  background: radial-gradient(circle at top right, var(--main-50), transparent 60%), var(--main-5);
  position: relative;
  overflow-x: hidden;
}

// Loading State
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 1rem;

  .loading-text {
    color: var(--gray-600);
    font-size: 0.95rem;
  }
}

// Error State
.error-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem;
}
.glass-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 0.75rem 2.5rem;
  background-color: var(--color-trans-light);
  backdrop-filter: blur(20px);
  // border-bottom: 1px solid var(--main-30);
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  box-shadow: 0 6px 25px rgba(3, 80, 101, 0.02);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.logo {
  display: flex;
  align-items: center;
  font-size: 1.4rem;
  font-weight: bold;
  color: var(--main-800);

  .logo-img {
    height: 2rem;
    margin-right: 0.6rem;
  }
}

.logo-text {
  font-size: 1.3rem;
  font-weight: 600;
}

.github-link a {
  display: flex;
  align-items: center;
  text-decoration: none;
  color: var(--gray-600);
  padding: 0.6rem 1rem;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  font-size: 0.9rem;
  font-weight: 500;

  &:hover {
    color: var(--gray-700);

    svg {
      transform: scale(1.1);
    }
  }

  svg {
    margin-right: 6px;
    transition: transform 0.3s ease;
    fill: currentColor;
  }

  // Dark mode styles
  :global(.dark) & {
    color: var(--gray-400);

    &:hover {
      color: var(--gray-300);
    }
  }
}

.hero-section {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 5rem 2rem 2rem;
}

.hero-layout {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 2.5rem;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  padding-top: 4rem;
}

.hero-content {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.reveal-up {
  opacity: 0;
  transform: translateY(14px);
  animation: revealUp 0.7s ease forwards;
}

.reveal-up.delay-1 {
  animation-delay: 120ms;
}

.hero-badge {
  color: var(--main-600);
  font-size: 0.92rem;
  letter-spacing: 0.04em;
  font-weight: 600;
  margin: 0;
}

.hero-badge-link {
  color: inherit;
  text-decoration: none;
}

.hero-badge-number {
  color: var(--main-700);
  text-decoration: underline;
  text-decoration-color: var(--main-500);
  text-underline-offset: 0.15em;
  text-decoration-thickness: 1.5px;
  font-weight: 700;
  transition:
    color 0.2s ease,
    text-decoration-color 0.2s ease;
}

.hero-badge-link:hover .hero-badge-number {
  color: var(--main-800);
  text-decoration-color: var(--main-700);
}

.hero-badge.typing::after {
  content: '';
  display: inline-block;
  width: 1px;
  height: 1em;
  margin-left: 6px;
  background: var(--main-600);
  vertical-align: -0.1em;
  animation: caretBlink 0.8s steps(1, end) infinite;
}

.title {
  font-size: clamp(2.5rem, 4vw, 4rem);
  font-weight: 800;
  margin: 0;
  background: linear-gradient(135deg, var(--main-900), var(--main-600));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  letter-spacing: -0.02em;
  line-height: 1.1;
}

.subtitle {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--gray-700);
  line-height: 1.4;
  margin: 0;
  min-height: calc(1.4em * 1.3);
}

.subtitle-switch-enter-active,
.subtitle-switch-leave-active {
  transition:
    opacity 0.32s ease,
    transform 0.32s ease;
}

.subtitle-switch-enter-from,
.subtitle-switch-leave-to {
  opacity: 0;
  transform: translateY(7px);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
}

.doc-text-link {
  color: var(--main-700);
  font-weight: 600;
  text-decoration: none;
  border-bottom: 1px dashed var(--main-300);
  padding-bottom: 0.15rem;
  transition:
    color 0.2s ease,
    border-color 0.2s ease;

  &:hover {
    color: var(--main-800);
    border-color: var(--main-500);
  }
}

.button-base {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 0.5rem 2.75rem;
  border-radius: 999px;
  font-size: 1.05rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  transition: all 0.25s ease;
  min-height: 52px;
}

.button-base.primary {
  background: linear-gradient(135deg, var(--main-600), var(--main-500));
  color: var(--gray-0);
  border-color: transparent;
  position: relative;
  isolation: isolate;

  &:hover {
    background: linear-gradient(135deg, var(--main-700), var(--main-600));
  }
}

.insight-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1.5rem;
}

.stat-card {
  background: var(--color-trans-light);
  backdrop-filter: blur(20px);
  padding: 1.5rem;
  border-radius: 1.5rem;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.03);
  animation: revealUp 0.7s ease forwards;
  animation-delay: calc(200ms + var(--card-stagger) * 100ms);
  opacity: 0;
  border: 1px solid var(--gray-50);
  transition: all 0.3s ease;

  &:hover {
    transform: translateY(-5px);
    border-color: var(--main-color);
    box-shadow: 0 15px 35px rgba(var(--main-color-rgb), 0.1);
  }

  .stat-headline {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
  }

  .stat-icon {
    color: var(--main-600);
  }

  .stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    margin: 0;
    color: var(--main-800);
  }

  .stat-label {
    font-size: 0.9rem;
    color: var(--gray-500);
    margin: 0;
    font-weight: 500;
  }

  .stat-description {
    font-size: 0.85rem;
    color: var(--gray-400);
    margin: 0.5rem 0 0;
    line-height: 1.4;
  }
}

.section {
  padding: 4rem 2rem;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.5rem;
  max-width: 1200px;
  margin: 0 auto;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 1.5rem;
  background: var(--color-trans-light);
  backdrop-filter: blur(20px);
  border-radius: 1.25rem;
  text-decoration: none;
  transition: all 0.3s ease;
  border: 1px solid var(--gray-50);

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.05);
    border-color: var(--main-color);
  }

  .action-icon {
    width: 3.5rem;
    height: 3.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--main-50);
    color: var(--main-600);
    border-radius: 1rem;
    transition: all 0.3s ease;
  }

  &:hover .action-icon {
    background: var(--main-600);
    color: white;
  }

  .action-meta {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .action-title {
    font-weight: 600;
    color: var(--gray-800);
    margin: 0;
  }

  .action-url {
    font-size: 0.8rem;
    color: var(--gray-400);
    margin: 0;
    word-break: break-all;
  }
}

.footer {
  padding: 4rem 2rem;
  border-top: 1px solid var(--main-30);
}

.footer-content {
  max-width: 1200px;
  margin: 0 auto;
  text-align: center;
}

.copyright {
  color: var(--gray-400);
  font-size: 0.9rem;
}

@keyframes revealUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes caretBlink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

.home-container {
  color: #10231e;
  background:
    linear-gradient(90deg, rgba(16, 111, 99, 0.08), transparent 38%),
    linear-gradient(180deg, #f7fbf8 0%, #eef6f2 100%);
}

.home-container::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(29, 83, 70, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(29, 83, 70, 0.06) 1px, transparent 1px);
  background-size: 34px 34px;
}

.home-container > * {
  position: relative;
  z-index: 1;
}

.glass-header {
  padding: 0.75rem 2rem;
  background: rgba(255, 255, 255, 0.86);
  border-bottom: 1px solid rgba(39, 83, 70, 0.12);
  box-shadow: none;
}

.logo {
  color: #16362d;
}

.logo-text {
  font-size: 1.15rem;
  letter-spacing: 0;
}

.github-link a {
  color: #47645b;
}

.hero-section {
  min-height: 100vh;
  padding: 6rem 2rem 2.5rem;
  justify-content: center;
}

.hero-layout {
  grid-template-columns: minmax(0, 1fr) minmax(360px, 520px);
  max-width: 1180px;
  gap: 3rem;
  padding-top: 0;
}

.hero-content {
  max-width: 640px;
  gap: 1.1rem;
}

.reveal-up.delay-2 {
  animation-delay: 180ms;
}

.hero-badge {
  width: fit-content;
  padding: 0.45rem 0.7rem;
  color: #245e50;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(36, 94, 80, 0.16);
  border-radius: 8px;
  font-size: 0.86rem;
  letter-spacing: 0;
}

.title {
  max-width: 680px;
  color: #10231e;
  background: none;
  font-size: 4rem;
  line-height: 1.02;
  letter-spacing: 0;
}

.subtitle {
  max-width: 620px;
  min-height: 2.8em;
  color: #2c5147;
  font-size: 1.28rem;
  font-weight: 650;
}

.hero-summary {
  max-width: 620px;
  margin: 0;
  color: #526b62;
  font-size: 1rem;
  line-height: 1.7;
}

.hero-actions {
  margin-top: 0.4rem;
}

.button-base {
  border-radius: 8px;
  min-height: 48px;
  padding: 0.55rem 1.45rem;
  font-size: 1rem;
}

.button-base.primary {
  background: #167567;
  box-shadow: 0 14px 30px rgba(22, 117, 103, 0.2);
}

.button-base.primary:hover {
  background: #0f5f54;
  transform: translateY(-1px);
}

.doc-text-link {
  color: #7a5a14;
  border-bottom-color: rgba(122, 90, 20, 0.32);
}

.doc-text-link:hover {
  color: #4f3b0f;
  border-color: #9d741c;
}

.graph-stage {
  width: 100%;
  min-width: 0;
  padding: 1rem;
  border: 1px solid rgba(39, 83, 70, 0.16);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(242, 249, 246, 0.9)),
    #f7fbf8;
  box-shadow: 0 24px 70px rgba(26, 54, 45, 0.1);
}

.graph-stage-header {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  color: #2d5148;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0;
}

.stage-dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  background: #d99a25;
  box-shadow: 0 0 0 5px rgba(217, 154, 37, 0.14);
}

.globe-shell {
  position: relative;
  width: min(100%, 500px);
  aspect-ratio: 1;
  margin: 0.6rem auto 0;
  transform: rotateX(var(--tilt-x)) rotateY(var(--tilt-y));
  transform-style: preserve-3d;
  transition: transform 0.18s ease;
}

.globe-grid,
.graph-links,
.globe-ring,
.knowledge-node,
.globe-core {
  position: absolute;
}

.globe-grid {
  inset: 8%;
  border: 1px solid rgba(23, 89, 78, 0.32);
  border-radius: 999px;
  background:
    linear-gradient(140deg, rgba(22, 117, 103, 0.08), transparent 54%),
    rgba(255, 255, 255, 0.38);
  box-shadow: inset 0 0 34px rgba(22, 117, 103, 0.1);
  animation: globeBreath 5s ease-in-out infinite;
}

.globe-ring {
  inset: 8%;
  border: 1px solid rgba(22, 117, 103, 0.18);
  border-radius: 999px;
}

.ring-main {
  inset: 0;
  border-color: rgba(22, 117, 103, 0.28);
}

.ring-tilt-a {
  transform: rotate(34deg) scaleX(0.56);
}

.ring-tilt-b {
  transform: rotate(-34deg) scaleX(0.56);
}

.ring-flat-a {
  transform: scaleY(0.44);
}

.ring-flat-b {
  transform: scaleY(0.72);
}

.graph-links {
  inset: 0;
  width: 100%;
  height: 100%;
  fill: none;
  transform: translateZ(22px);
}

.graph-links path {
  stroke: rgba(22, 117, 103, 0.42);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-dasharray: 460;
  stroke-dashoffset: 460;
  animation: drawLink 1.8s ease forwards, linkPulse 4.6s ease-in-out infinite;
  animation-delay: var(--link-delay), calc(1.8s + var(--link-delay));
}

.knowledge-node {
  width: 4.4rem;
  height: 4.4rem;
  margin: -2.2rem 0 0 -2.2rem;
  display: grid;
  place-items: center;
  border: 1px solid rgba(35, 80, 69, 0.18);
  border-radius: 999px;
  background: #ffffff;
  color: #173a32;
  font-size: 0.72rem;
  font-weight: 800;
  cursor: default;
  transform: translateZ(46px);
  box-shadow: 0 12px 28px rgba(19, 54, 45, 0.12);
  animation: nodeFloat 4.8s ease-in-out infinite;
  animation-delay: var(--node-delay);
}

.knowledge-node.vector {
  border-color: rgba(31, 107, 178, 0.24);
  color: #1d5c86;
}

.knowledge-node.graph {
  border-color: rgba(217, 154, 37, 0.32);
  color: #7a5a14;
}

.knowledge-node.answer {
  border-color: rgba(19, 126, 89, 0.3);
  color: #137e59;
}

.node-pulse {
  position: absolute;
  inset: -0.35rem;
  border: 1px solid currentColor;
  border-radius: inherit;
  opacity: 0.16;
  animation: nodePulse 2.8s ease-out infinite;
  animation-delay: var(--node-delay);
}

.node-label {
  position: relative;
  z-index: 1;
  max-width: 4rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.globe-core {
  inset: 38%;
  display: grid;
  place-items: center;
  border: 1px solid rgba(22, 117, 103, 0.22);
  border-radius: 999px;
  background: #16362d;
  color: #ffffff;
  font-size: 0.9rem;
  font-weight: 800;
  transform: translateZ(68px);
  box-shadow: 0 18px 36px rgba(13, 47, 39, 0.28);
}

.flow-legend {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.5rem;
  margin-top: 0.8rem;
}

.flow-legend span {
  min-height: 2.2rem;
  display: grid;
  place-items: center;
  padding: 0.35rem 0.45rem;
  border: 1px solid rgba(39, 83, 70, 0.12);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.72);
  color: #456359;
  font-size: 0.72rem;
  font-weight: 700;
  text-align: center;
}

.section {
  padding: 2.4rem 2rem;
}

.proof-section {
  padding-top: 0;
}

.proof-grid,
.action-grid {
  max-width: 1180px;
}

.proof-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
  margin: 0 auto;
}

.stat-card,
.action-card {
  border-radius: 8px;
  border-color: rgba(39, 83, 70, 0.13);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 16px 42px rgba(26, 54, 45, 0.07);
}

.stat-card {
  padding: 1.15rem;
}

.stat-card:hover,
.action-card:hover {
  border-color: rgba(22, 117, 103, 0.35);
  box-shadow: 0 20px 46px rgba(26, 54, 45, 0.11);
}

.stat-icon,
.stat-value {
  color: #167567;
}

.stat-label,
.stat-description {
  color: #5d746c;
}

.action-card {
  padding: 1.2rem;
}

.action-card .action-icon {
  border-radius: 8px;
  background: #edf6f2;
  color: #167567;
}

.action-card:hover .action-icon {
  background: #167567;
}

.footer {
  padding: 2.5rem 2rem;
  border-color: rgba(39, 83, 70, 0.12);
}

@keyframes drawLink {
  to {
    stroke-dashoffset: 0;
  }
}

@keyframes linkPulse {
  0%,
  100% {
    opacity: 0.48;
  }
  50% {
    opacity: 0.9;
  }
}

@keyframes nodeFloat {
  0%,
  100% {
    transform: translateZ(46px) translateY(0);
  }
  50% {
    transform: translateZ(46px) translateY(-8px);
  }
}

@keyframes nodePulse {
  0% {
    transform: scale(0.88);
    opacity: 0.2;
  }
  100% {
    transform: scale(1.42);
    opacity: 0;
  }
}

@keyframes globeBreath {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.015);
  }
}

@media (max-width: 1080px) {
  .hero-layout {
    grid-template-columns: 1fr;
    gap: 2rem;
  }

  .graph-stage {
    max-width: 620px;
  }

  .proof-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .glass-header {
    padding: 0.7rem 1rem;
  }

  .logo-text {
    font-size: 1rem;
  }

  .github-link {
    display: none;
  }

  .hero-section {
    padding: 5.4rem 1rem 2rem;
  }

  .title {
    font-size: 2.75rem;
  }

  .subtitle {
    font-size: 1.08rem;
  }

  .hero-summary {
    font-size: 0.95rem;
  }

  .graph-stage {
    padding: 0.8rem;
  }

  .knowledge-node {
    width: 3.7rem;
    height: 3.7rem;
    margin: -1.85rem 0 0 -1.85rem;
    font-size: 0.64rem;
  }

  .flow-legend,
  .proof-grid,
  .action-grid {
    grid-template-columns: 1fr;
  }

  .section {
    padding: 1.5rem 1rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .reveal-up,
  .graph-links path,
  .knowledge-node,
  .node-pulse,
  .globe-grid {
    animation: none;
  }

  .globe-shell {
    transform: none;
  }
}
</style>
