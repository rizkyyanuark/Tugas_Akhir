<template>
  <div class="dashboard-view">
    <div class="dashboard-header">
      <h1 class="dashboard-title">
        <BarChart3 :size="28" class="title-icon" />
        Dashboard Akademik
      </h1>
      <p class="dashboard-subtitle">Statistik Knowledge Graph Informatika UNESA</p>
    </div>

    <!-- Stats Cards -->
    <div class="stats-grid">
      <div class="stat-card papers" @click="refreshStats">
        <div class="stat-icon-wrap">
          <FileText :size="24" />
        </div>
        <div class="stat-info">
          <p class="stat-value">{{ stats.papersCount !== null ? stats.papersCount.toLocaleString() : '—' }}</p>
          <p class="stat-label">Total Paper</p>
          <p class="stat-desc">Paper akademik terindeks</p>
        </div>
      </div>

      <div class="stat-card lecturers">
        <div class="stat-icon-wrap">
          <Users :size="24" />
        </div>
        <div class="stat-info">
          <p class="stat-value">{{ stats.lecturersCount !== null ? stats.lecturersCount.toLocaleString() : '—' }}</p>
          <p class="stat-label">Total Dosen</p>
          <p class="stat-desc">Dosen Informatika UNESA</p>
        </div>
      </div>

      <div class="stat-card kg-nodes">
        <div class="stat-icon-wrap">
          <Network :size="24" />
        </div>
        <div class="stat-info">
          <p class="stat-value">{{ stats.kgNodesCount !== null ? stats.kgNodesCount.toLocaleString() : '—' }}</p>
          <p class="stat-label">Knowledge Graph Nodes</p>
          <p class="stat-desc">Entity nodes di Neo4j</p>
        </div>
      </div>

      <div class="stat-card conversations">
        <div class="stat-icon-wrap">
          <MessageSquare :size="24" />
        </div>
        <div class="stat-info">
          <p class="stat-value">{{ stats.conversationsCount !== null ? stats.conversationsCount.toLocaleString() : '—' }}</p>
          <p class="stat-label">Total Percakapan</p>
          <p class="stat-desc">Sesi chatbot MCP</p>
        </div>
      </div>
    </div>

    <!-- Details Section -->
    <div class="details-section">
      <div class="detail-card">
        <h3 class="detail-title">
          <Database :size="18" />
          Sumber Data
        </h3>
        <div class="detail-list">
          <div class="detail-item">
            <span class="detail-key">Supabase</span>
            <span class="detail-val active">Connected</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Neo4j Graph DB</span>
            <span class="detail-val" :class="stats.kgNodesCount !== null ? 'active' : 'inactive'">
              {{ stats.kgNodesCount !== null ? 'Connected' : 'Offline' }}
            </span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Milvus Vector DB</span>
            <span class="detail-val active">Connected</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Redis Cache</span>
            <span class="detail-val active">Connected</span>
          </div>
        </div>
      </div>

      <div class="detail-card">
        <h3 class="detail-title">
          <Activity :size="18" />
          Pipeline ETL
        </h3>
        <div class="detail-list">
          <div class="detail-item">
            <span class="detail-key">Scraping Scopus</span>
            <span class="detail-val">Airflow DAG</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Scraping Scholar</span>
            <span class="detail-val">Airflow DAG</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">KG Construction</span>
            <span class="detail-val">Webhook Trigger</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Vector Embedding</span>
            <span class="detail-val">Sentence-Transformers</span>
          </div>
        </div>
      </div>

      <div class="detail-card">
        <h3 class="detail-title">
          <Bot :size="18" />
          MCP Agent
        </h3>
        <div class="detail-list">
          <div class="detail-item">
            <span class="detail-key">LLM Provider</span>
            <span class="detail-val">Groq (Llama 4)</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Retrieval</span>
            <span class="detail-val">LightRAG + Neo4j</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Framework</span>
            <span class="detail-val">LangGraph v1</span>
          </div>
          <div class="detail-item">
            <span class="detail-key">Monitoring</span>
            <span class="detail-val">Opik / Langfuse</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading overlay -->
    <div v-if="isLoading" class="loading-overlay">
      <a-spin size="large" />
      <p>Memuat statistik...</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import {
  BarChart3,
  FileText,
  Users,
  Network,
  MessageSquare,
  Database,
  Activity,
  Bot
} from 'lucide-vue-next'
import { dashboardApi } from '@/apis/dashboard_api'

const isLoading = ref(false)
const stats = reactive({
  papersCount: null,
  lecturersCount: null,
  kgNodesCount: null,
  conversationsCount: null
})

const loadStats = async () => {
  isLoading.value = true
  try {
    const data = await dashboardApi.getAcademicStats()
    if (data) {
      stats.papersCount = data.papers_count ?? null
      stats.lecturersCount = data.lecturers_count ?? null
      stats.kgNodesCount = data.kg_nodes_count ?? null
      stats.conversationsCount = data.conversations_count ?? null
    }
  } catch (error) {
    console.error('Failed to load academic stats:', error)
  } finally {
    isLoading.value = false
  }
}

const refreshStats = () => {
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
  padding: 32px 40px;
  background: var(--main-5, #f8f9fc);
  position: relative;
  overflow-y: auto;
}

.dashboard-header {
  margin-bottom: 32px;

  .dashboard-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 24px;
    font-weight: 700;
    color: var(--gray-900, #1a1a2e);
    margin: 0 0 6px 0;

    .title-icon {
      color: var(--main-color, #4f46e5);
    }
  }

  .dashboard-subtitle {
    font-size: 14px;
    color: var(--gray-500, #6b7280);
    margin: 0;
  }
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--gray-0, #ffffff);
  border-radius: 16px;
  padding: 24px;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  border: 1px solid var(--gray-100, #e5e7eb);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: default;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
  }

  .stat-icon-wrap {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  &.papers .stat-icon-wrap {
    background: linear-gradient(135deg, #dbeafe, #bfdbfe);
    color: #2563eb;
  }

  &.lecturers .stat-icon-wrap {
    background: linear-gradient(135deg, #dcfce7, #bbf7d0);
    color: #16a34a;
  }

  &.kg-nodes .stat-icon-wrap {
    background: linear-gradient(135deg, #fef3c7, #fde68a);
    color: #d97706;
  }

  &.conversations .stat-icon-wrap {
    background: linear-gradient(135deg, #ede9fe, #ddd6fe);
    color: #7c3aed;
  }

  .stat-info {
    flex: 1;

    .stat-value {
      font-size: 28px;
      font-weight: 800;
      color: var(--gray-900, #1a1a2e);
      margin: 0;
      line-height: 1.2;
      font-variant-numeric: tabular-nums;
    }

    .stat-label {
      font-size: 14px;
      font-weight: 600;
      color: var(--gray-700, #374151);
      margin: 4px 0 2px;
    }

    .stat-desc {
      font-size: 12px;
      color: var(--gray-400, #9ca3af);
      margin: 0;
    }
  }
}

.details-section {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
}

.detail-card {
  background: var(--gray-0, #ffffff);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--gray-100, #e5e7eb);

  .detail-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 600;
    color: var(--gray-800, #1f2937);
    margin: 0 0 16px 0;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--gray-100, #e5e7eb);
  }

  .detail-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .detail-item {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .detail-key {
      font-size: 13px;
      color: var(--gray-600, #4b5563);
    }

    .detail-val {
      font-size: 13px;
      font-weight: 500;
      color: var(--gray-800, #1f2937);
      padding: 2px 10px;
      border-radius: 6px;
      background: var(--gray-50, #f9fafb);

      &.active {
        background: #dcfce7;
        color: #16a34a;
      }

      &.inactive {
        background: #fee2e2;
        color: #dc2626;
      }
    }
  }
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  z-index: 10;
  border-radius: 16px;

  p {
    color: var(--gray-500);
    font-size: 14px;
  }
}

@media (max-width: 768px) {
  .dashboard-view {
    padding: 20px 16px;
  }

  .stats-grid {
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .stat-card {
    padding: 16px;

    .stat-info .stat-value {
      font-size: 22px;
    }
  }

  .details-section {
    grid-template-columns: 1fr;
  }
}
</style>
