<template>
  <div class="dashboard-view animate-fade-in">
    <!-- Mesh Background Ornaments -->
    <div class="mesh-background">
      <div class="glow-sphere sphere-1"></div>
      <div class="glow-sphere sphere-2"></div>
      <div class="glow-sphere sphere-3"></div>
    </div>

    <div class="dashboard-container">
      <!-- Header Section -->
      <header class="dashboard-header animate-fade-in">
        <div class="title-row">
            <h1 class="dashboard-title">
            <div class="icon-pulse">
              <BarChart3 :size="28" />
            </div>
            <span>Antigravity Intelligence</span>
          </h1>
          
          <div class="badge-group">
            <div class="status-badge live">
              <div class="dot"></div>
              Sistem Operasional
            </div>
            <button class="refresh-btn" @click="refreshStats" :class="{ rotating: isLoading }">
              <RefreshCw :size="18" />
            </button>
          </div>
        </div>
        <p class="dashboard-subtitle">Pusat monitoring data, wawasan riset, dan kesehatan Knowledge Graph</p>
      </header>

      <!-- Stats Grid -->
      <div class="stats-grid">
        <div 
          v-for="(card, key) in statCards" 
          :key="key"
          class="stat-card glass-card animate-slide-up"
          :style="{ '--delay': card.delay, '--accent-color': card.accent }"
        >
          <div class="card-glow"></div>
          <div class="stat-header">
            <div class="stat-icon-wrap">
              <component :is="card.icon" :size="24" />
            </div>
            <div v-if="card.trend" class="stat-trend positive">{{ card.trend }}</div>
          </div>
          <div class="stat-value-container">
            <span class="stat-value">{{ formatNumber(stats[card.key]) }}</span>
            <span class="stat-unit" v-if="card.key === 'kgNodesCount'">nodes</span>
          </div>
          <h3 class="stat-label">{{ card.label }}</h3>
          <div class="stat-progress">
            <div class="progress-bar" :style="{ width: card.progress + '%' }">
              <div class="progress-glow"></div>
            </div>
          </div>
          <p class="stat-desc">{{ card.desc }}</p>
        </div>
      </div>

      <!-- Main Layout Section -->
      <div class="dashboard-content-layout">
        <!-- Infrastruktur Status -->
        <section class="content-panel glass-card animate-slide-up" style="--delay: 0.5s">
          <div class="panel-header">
            <div class="header-left">
              <div class="panel-icon"><Database :size="20" /></div>
              <h3>Infrastruktur</h3>
            </div>
            <span class="panel-status">Stabil</span>
          </div>

          <div class="data-items">
            <div class="data-row">
              <div class="data-label">
                <div class="system-dot online"></div>
                Neo4j KG
              </div>
              <div class="data-meta">Klaster Produksi</div>
              <div class="data-status">LATENSI 24ms</div>
            </div>
            <div class="data-row">
              <div class="data-label">
                <div class="system-dot online"></div>
                Vector DB
              </div>
              <div class="data-meta">Milvus Search Engine</div>
              <div class="data-status">99.8% HIT</div>
            </div>
            <div class="data-row">
              <div class="data-label">
                <div class="system-dot online"></div>
                LLM Core
              </div>
              <div class="data-meta">Gemini 1.5 Pro (Aktif)</div>
              <div class="data-status">ONLINE</div>
            </div>
          </div>
          
          <div class="panel-footer">
            <button class="action-btn secondary" @click="refreshStats"><Activity :size="16" /> Lihat Log</button>
            <button class="action-btn secondary" @click="refreshStats"><RefreshCw :size="16" /> Sinkron KG</button>
          </div>
        </section>

        <!-- Pipeline Status -->
        <section class="content-panel glass-card animate-slide-up" style="--delay: 0.6s">
          <div class="panel-header">
            <div class="header-left">
              <div class="panel-icon"><Cpu :size="20" /></div>
              <h3>Pipeline Riset Aktif</h3>
            </div>
            <Activity :size="20" color="#4f46e5" />
          </div>

          <div class="pipeline-flow">
            <div class="pipeline-node">
              <div class="node-circle active"><Download :size="16" /></div>
              <div class="node-content">
                <p class="node-name">Ingesti Data</p>
                <p class="node-status">Memproses ID-242 (Paper)</p>
              </div>
            </div>
            <div class="pipeline-connector"></div>
            <div class="pipeline-node">
              <div class="node-circle active"><Zap :size="16" /></div>
              <div class="node-content">
                <p class="node-name">Ekstraksi Entitas</p>
                <p class="node-status">Menganalisis relasi...</p>
              </div>
            </div>
            <div class="pipeline-connector" style="opacity: 0.3"></div>
            <div class="pipeline-node">
              <div class="node-circle"><Globe :size="16" /></div>
              <div class="node-content">
                <p class="node-name">Pengayaan KG</p>
                <p class="node-status">Menunggu ekstraksi</p>
              </div>
            </div>
          </div>
        </section>

        <!-- Agent Status -->
        <section class="content-panel glass-card animate-slide-up" style="--delay: 0.7s">
          <div class="panel-header">
            <div class="header-left">
              <div class="panel-icon"><Bot :size="20" /></div>
              <h3>Asisten Pintar</h3>
            </div>
            <div class="status-badge live">Aktif</div>
          </div>

          <div class="agent-config">
            <div class="config-item">
              <span class="config-label">Mode Memori</span>
              <span class="config-value">Context-Aware</span>
            </div>
            <div class="config-item">
              <span class="config-label">Kualitas Respon</span>
              <span class="config-value highlight">ULTRA_HD</span>
            </div>
          </div>

          <div class="panel-footer">
            <button class="action-btn primary">Konfigurasi AI Agent</button>
          </div>
        </section>
      </div>
    </div>

    <!-- Full Screen Premium Loader -->
    <transition name="premium-fade">
      <div v-if="isLoading" class="premium-loader">
        <div class="loader-content">
          <div class="loader-visual">
            <div class="orbit"><div class="planet"></div></div>
            <div class="core-glow"></div>
          </div>
          <div class="loader-text">
            <span class="main-text">ANTIGRAVITY CORE</span>
            <span class="sub-text">Mensinkronisasi Pengetahuan...</span>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, markRaw } from 'vue'
import {
  BarChart3,
  FileText,
  Users,
  Network,
  MessageSquare,
  Database,
  Activity,
  Bot,
  RefreshCw,
  Download,
  Cpu,
  Zap,
  Globe
} from 'lucide-vue-next'
import { dashboardApi } from '@/apis/dashboard_api'

const isLoading = ref(false)
const stats = reactive({
  papersCount: 0,
  lecturersCount: 0,
  kgNodesCount: 0,
  conversationsCount: 0
})

const statCards = ref([
  {
    key: 'papersCount',
    label: 'Total Paper',
    type: 'papers',
    icon: markRaw(FileText),
    delay: '0.1s',
    trend: '+12%',
    progress: 85,
    accent: '#3b82f6',
    desc: 'Aktivitas riset terindeks'
  },
  {
    key: 'lecturersCount',
    label: 'Total Dosen',
    type: 'lecturers',
    icon: markRaw(Users),
    delay: '0.2s',
    progress: 100,
    accent: '#10b981',
    desc: 'Dosen Informatika aktif'
  },
  {
    key: 'kgNodesCount',
    label: 'KG Entities',
    type: 'kg-nodes',
    icon: markRaw(Network),
    delay: '0.3s',
    trend: '+243',
    progress: 65,
    accent: '#f59e0b',
    desc: 'Relasi pengetahuan Neo4j'
  },
  {
    key: 'conversationsCount',
    label: 'Sesi Chat',
    type: 'conversations',
    icon: markRaw(MessageSquare),
    delay: '0.4s',
    progress: 40,
    accent: '#8b5cf6',
    desc: 'Interaksi chatbot pintar'
  }
])

const formatNumber = (num) => {
  if (num === null || num === undefined) return '—'
  return num.toLocaleString()
}

const loadStats = async () => {
  isLoading.value = true
  try {
    const data = await dashboardApi.getAcademicStats()
    if (data) {
      // Simulate slight delay for smooth animation transition
      setTimeout(() => {
        stats.papersCount = data.papers_count ?? 0
        stats.lecturersCount = data.lecturers_count ?? 0
        stats.kgNodesCount = data.kg_nodes_count ?? 0
        stats.conversationsCount = data.conversations_count ?? 0
        isLoading.value = false
      }, 600)
    }
  } catch (error) {
    console.error('Failed to load academic stats:', error)
    isLoading.value = false
  }
}

const refreshStats = () => {
  if (isLoading.value) return
  loadStats()
}

onMounted(() => {
  loadStats()
})
</script>

<style lang="less" scoped>
.dashboard-view {
  width: 100%;
  min-height: 100vh;
  background: #f8fafc;
  padding: 40px 24px;
  position: relative;
  overflow: hidden;
  color: #1e293b;
}

/* Mesh Background Ornaments */
.mesh-background {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: 
    var(--mesh-grad-1),
    var(--mesh-grad-2),
    var(--mesh-grad-3),
    var(--mesh-grad-4);

  .glow-sphere {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.4;
    animation: float 20s infinite alternate ease-in-out;

    &.sphere-1 {
      width: 400px;
      height: 400px;
      background: #4f46e5;
      top: -100px;
      left: -100px;
    }
    &.sphere-2 {
      width: 500px;
      height: 500px;
      background: #9333ea;
      bottom: -150px;
      right: -100px;
      animation-delay: -5s;
    }
    &.sphere-3 {
      width: 300px;
      height: 300px;
      background: #0ea5e9;
      top: 40%;
      right: 10%;
      animation-delay: -10s;
    }
  }
}

.dashboard-container {
  max-width: 1400px;
  margin: 0 auto;
  position: relative;
  z-index: 1;
}

/* Glassmorphism Common */
.glass-card {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(16px) saturate(180%);
  -webkit-backdrop-filter: blur(16px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.4);
  box-shadow: var(--shadow-premium);
  border-radius: var(--radius-xl);
  transition: var(--transition-bounce);
}

/* Header */
.dashboard-header {
  margin-bottom: 48px;

  .title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }

  .dashboard-title {
    display: flex;
    align-items: center;
    gap: 20px;
    font-size: 36px;
    font-weight: 900;
    letter-spacing: -0.03em;
    margin: 0;
    
    span {
      background: linear-gradient(135deg, #0f172a 0%, #334155 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .icon-pulse {
      background: linear-gradient(135deg, #4f46e5, #0ea5e9);
      padding: 12px;
      border-radius: 16px;
      display: flex;
      color: #fff;
      box-shadow: 0 12px 24px rgba(79, 70, 229, 0.25);
      position: relative;

      &::after {
        content: '';
        position: absolute;
        inset: -4px;
        border-radius: 20px;
        border: 2px solid #4f46e5;
        opacity: 0.3;
        animation: pulse-ring 2s infinite;
      }
    }
  }

  .badge-group {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .status-badge {
    padding: 8px 16px;
    border-radius: 100px;
    font-size: 12px;
    font-weight: 800;
    background: #fff;
    border: 1px solid rgba(229, 231, 235, 0.5);
    display: flex;
    align-items: center;
    gap: 8px;
    color: #475569;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03);

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 12px #10b981;
      animation: blink 1.5s infinite;
    }
  }

  .refresh-btn {
    width: 42px;
    height: 42px;
    border-radius: 12px;
    border: none;
    background: #fff;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #64748b;
    transition: var(--transition-smooth);
    box-shadow: 0 4px 12px rgba(0,0,0,0.05);

    &:hover {
      background: #f8fafc;
      color: #4f46e5;
      transform: rotate(45deg) scale(1.1);
      box-shadow: 0 8px 20px rgba(79, 70, 229, 0.15);
    }

    &.rotating svg {
      animation: spin 1s linear infinite;
    }
  }

  .dashboard-subtitle {
    font-size: 18px;
    color: #64748b;
    font-weight: 500;
    margin: 0;
  }
}

/* Stats Cards */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 28px;
  margin-bottom: 48px;
}

.stat-card {
  padding: 32px;
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.5);

  &:hover {
    transform: translateY(-10px) scale(1.02);
    background: rgba(255, 255, 255, 0.9);
    border-color: var(--accent-color);
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.15);

    .card-glow { opacity: 0.2; }
    .stat-icon-wrap { transform: rotate(-5deg) scale(1.15); }
    .progress-glow { animation: shimmer 1.5s infinite; }
  }

  .card-glow {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 200%;
    height: 200%;
    transform: translate(-50%, -50%);
    background: radial-gradient(circle, var(--accent-color) 0%, transparent 70%);
    opacity: 0.05;
    transition: opacity 0.5s;
    pointer-events: none;
  }

  .stat-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    position: relative;
    z-index: 1;
  }

  .stat-icon-wrap {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #fff;
    color: var(--accent-color);
    box-shadow: 0 8px 16px rgba(0,0,0,0.05);
    transition: var(--transition-bounce);
  }

  .stat-trend {
    font-size: 13px;
    font-weight: 800;
    padding: 6px 12px;
    border-radius: 8px;
    background: #f0fdf4;
    color: #166534;
    border: 1px solid #dcfce7;
  }

  .stat-value-container {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 8px;
  }

  .stat-value {
    font-size: 42px;
    font-weight: 900;
    color: #0f172a;
    line-height: 1;
    letter-spacing: -2px;
  }

  .stat-unit {
    font-size: 16px;
    font-weight: 700;
    color: #64748b;
  }

  .stat-label {
    font-size: 16px;
    font-weight: 700;
    color: #475569;
    margin: 0 0 16px;
  }

  .stat-progress {
    height: 8px;
    background: #f1f5f9;
    border-radius: 100px;
    margin-bottom: 16px;
    overflow: hidden;

    .progress-bar {
      height: 100%;
      background: var(--accent-color);
      border-radius: 100px;
      position: relative;
    }

    .progress-glow {
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
      transform: translateX(-100%);
    }
  }

  .stat-desc {
    font-size: 13px;
    font-weight: 500;
    color: #94a3b8;
    margin: 0;
  }
}

/* Panels */
.dashboard-content-layout {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 28px;
}

.content-panel {
  padding: 36px;
  
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 32px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    .panel-icon {
      width: 48px;
      height: 48px;
      border-radius: 14px;
      background: #f8fafc;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #334155;
      box-shadow: inset 0 2px 4px rgba(0,0,0,0.02);
    }

    h3 {
      font-size: 20px;
      font-weight: 800;
      color: #1e293b;
      margin: 0;
    }

    .panel-status {
      font-size: 12px;
      font-weight: 800;
      color: #059669;
      background: #ecfdf5;
      padding: 6px 14px;
      border-radius: 100px;
      border: 1px solid #d1fae5;
    }
  }
}

/* Infrastructure */
.data-items {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.data-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  background: rgba(255,255,255,0.4);
  border-radius: 14px;
  border: 1px solid rgba(226, 232, 240, 0.5);
  transition: var(--transition-smooth);

  &:hover {
    background: #fff;
    transform: translateX(8px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.03);
  }

  .data-label {
    display: flex;
    align-items: center;
    gap: 14px;
    font-weight: 700;
    font-size: 15px;
    
    .system-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #cbd5e1;
      &.online { background: #10b981; box-shadow: 0 0 10px rgba(16, 185, 129, 0.5); }
      &.offline { background: #ef4444; }
    }
  }

  .data-meta {
    font-size: 14px;
    color: #64748b;
    margin-left: 20px;
    flex: 1;
  }

  .data-status {
    font-size: 12px;
    font-weight: 900;
    color: #475569;
    letter-spacing: 0.05em;
  }
}

/* Pipeline Flow */
.pipeline-flow {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px 0 10px 24px;
}

.pipeline-node {
  display: flex;
  align-items: center;
  gap: 20px;
  position: relative;

  .node-circle {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: #fff;
    border: 1px solid #e2e8f0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #64748b;
    z-index: 2;
    transition: var(--transition-bounce);

    &.active {
      border-color: #4f46e5;
      color: #fff;
      background: #4f46e5;
      box-shadow: 0 8px 16px rgba(79, 70, 229, 0.3);
    }
  }

  .node-content {
    .node-name { font-weight: 800; font-size: 15px; color: #1e293b; margin: 0; }
    .node-status { font-size: 13px; color: #64748b; margin: 4px 0 0; }
  }
}

.pipeline-connector {
  width: 2px;
  height: 32px;
  background: linear-gradient(to bottom, #4f46e5, #e2e8f0);
  margin-left: 19px;
}

/* Agent Config */
.agent-config {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 32px;
}

.config-item {
  background: #fff;
  padding: 20px;
  border-radius: 16px;
  border: 1px solid #f1f5f9;
  box-shadow: 0 2px 6px rgba(0,0,0,0.02);
  
  .config-label {
    display: block;
    font-size: 12px;
    font-weight: 800;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
  }

  .config-value {
    font-weight: 800;
    font-size: 15px;
    color: #334155;
    &.highlight { color: #4f46e5; }
  }
}

.panel-footer {
  margin-top: auto;
  display: flex;
  gap: 16px;

  .action-btn {
    flex: 1;
    padding: 16px;
    border-radius: 14px;
    font-weight: 800;
    font-size: 14px;
    cursor: pointer;
    transition: var(--transition-smooth);
    border: none;

    &.primary {
      background: #4f46e5;
      color: #fff;
      box-shadow: 0 8px 20px rgba(79, 70, 229, 0.2);
      &:hover { background: #4338ca; transform: translateY(-2px); box-shadow: 0 12px 24px rgba(79, 70, 229, 0.3); }
    }

    &.secondary {
      background: #fff;
      border: 1px solid #e2e8f0;
      color: #475569;
      &:hover { background: #f8fafc; transform: translateY(-2px); }
    }
  }
}

/* Premium Loader */
.premium-loader {
  position: fixed;
  inset: 0;
  background: #f8fafc;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;

  .loader-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 40px;
  }

  .loader-visual {
    position: relative;
    width: 120px;
    height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .orbit {
    position: absolute;
    width: 100%;
    height: 100%;
    border: 2px solid rgba(79, 70, 229, 0.1);
    border-radius: 50%;
    animation: spin 3s linear infinite;

    .planet {
      position: absolute;
      top: -6px;
      left: 50%;
      width: 12px;
      height: 12px;
      background: #4f46e5;
      border-radius: 50%;
      box-shadow: 0 0 20px #4f46e5;
    }
  }

  .core-glow {
    width: 40px;
    height: 40px;
    background: #4f46e5;
    border-radius: 50%;
    filter: blur(20px);
    animation: pulse-core 1.5s infinite alternate ease-in-out;
  }

  .loader-text {
    text-align: center;
    display: flex;
    flex-direction: column;
    gap: 8px;

    .main-text {
      font-size: 14px;
      font-weight: 900;
      color: #0f172a;
      letter-spacing: 0.3em;
    }
    .sub-text {
      font-size: 13px;
      color: #64748b;
      font-weight: 500;
    }
  }
}

/* Base Animations */
@keyframes float {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(50px, 50px) scale(1.1); }
}

@keyframes spin { to { transform: rotate(360deg); } }

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes pulse-ring {
  0% { transform: scale(0.95); opacity: 0.3; }
  50% { transform: scale(1.1); opacity: 0.1; }
  100% { transform: scale(0.95); opacity: 0.3; }
}

@keyframes pulse-core {
  from { transform: scale(0.8); opacity: 0.5; }
  to { transform: scale(1.2); opacity: 1; }
}

@keyframes shimmer {
  from { transform: translateX(-100%); }
  to { transform: translateX(100%); }
}

/* Transitions */
.animate-fade-in { animation: fadeIn 0.8s ease-out forwards; }
.animate-slide-up { 
  opacity: 0;
  animation: slideUp 0.6s ease-out forwards;
  animation-delay: var(--delay, 0s);
}

.premium-fade-enter-active, .premium-fade-leave-active {
  transition: opacity 0.8s ease;
}
.premium-fade-enter-from, .premium-fade-leave-to {
  opacity: 0;
}

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideUp { 
  from { opacity: 0; transform: translateY(30px); } 
  to { opacity: 1; transform: translateY(0); } 
}

/* Layout Adjustments */
@media (max-width: 1200px) {
  .dashboard-content-layout { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .dashboard-view { padding: 30px 16px; }
  .dashboard-header .dashboard-title { font-size: 28px; }
  .stats-grid { grid-template-columns: 1fr; }
  .agent-config { grid-template-columns: 1fr; }
}
</style>
