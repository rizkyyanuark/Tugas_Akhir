<template>
  <div class="trending-topics-card">
    <div class="card-header">
      <div class="header-title">
        <TrendingUp class="icon" />
        <span>Trending Research Topics</span>
      </div>
      <div class="header-action">
        <button class="btn-refresh" @click="refreshTopics">
          <RefreshCw :class="{ 'spinning': refreshing }" class="icon" />
        </button>
      </div>
    </div>
    <div class="topics-content">
      <div class="topics-cloud">
        <div 
          v-for="topic in topics" 
          :key="topic.name"
          class="topic-tag"
          :style="{ 
            fontSize: getFontSize(topic.score),
            opacity: getOpacity(topic.score),
            background: getBgColor(topic.score)
          }"
        >
          {{ topic.name }}
          <span class="count">{{ topic.count }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { TrendingUp, RefreshCw } from 'lucide-vue-next'

const refreshing = ref(false)
const topics = ref([
  { name: 'Knowledge Graph', count: 156, score: 95 },
  { name: 'RAG Systems', count: 124, score: 88 },
  { name: 'LLM Agents', count: 98, score: 82 },
  { name: 'Informatics', count: 85, score: 75 },
  { name: 'Data Mining', count: 72, score: 70 },
  { name: 'Machine Learning', count: 64, score: 65 },
  { name: 'Semantic Web', count: 58, score: 60 },
  { name: 'Graph DB', count: 42, score: 55 },
  { name: 'NLP', count: 38, score: 50 },
  { name: 'Cloud Computing', count: 31, score: 45 }
])

const getFontSize = (score) => `${Math.max(12, (score / 100) * 20)}px`
const getOpacity = (score) => Math.max(0.6, score / 100)
const getBgColor = (score) => {
  if (score > 80) return 'var(--color-primary-50)'
  if (score > 60) return 'var(--gray-50)'
  return 'transparent'
}

const refreshTopics = () => {
  refreshing.value = true
  setTimeout(() => {
    refreshing.value = false
  }, 1000)
}
</script>

<style lang="less" scoped>
.trending-topics-card {
  background: var(--bg-sider);
  backdrop-filter: blur(20px);
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  padding: 24px;
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;

  &:hover {
    border-color: var(--main-color);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.05);
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;

    .header-title {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 16px;
      font-weight: 600;
      color: var(--gray-2000);

      .icon {
        width: 20px;
        height: 20px;
        color: var(--main-color);
      }
    }

    .btn-refresh {
      background: transparent;
      border: none;
      cursor: pointer;
      color: var(--gray-500);
      padding: 4px;
      border-radius: 4px;
      transition: all 0.2s;

      &:hover {
        color: var(--main-color);
        background: var(--color-primary-50);
      }

      .icon {
        width: 18px;
        height: 18px;
        
        &.spinning {
          animation: spin 1s linear infinite;
        }
      }
    }
  }

  .topics-content {
    flex: 1;
    overflow-y: auto;

    .topics-cloud {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: center;
      padding: 10px 0;
    }

    .topic-tag {
      padding: 6px 12px;
      border-radius: 20px;
      border: 1px solid var(--gray-150);
      color: var(--gray-800);
      white-space: nowrap;
      cursor: pointer;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      gap: 6px;

      &:hover {
        border-color: var(--main-color);
        color: var(--main-color);
        transform: scale(1.05);
      }

      .count {
        font-size: 10px;
        background: var(--gray-100);
        padding: 2px 6px;
        border-radius: 10px;
        color: var(--gray-500);
      }
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
