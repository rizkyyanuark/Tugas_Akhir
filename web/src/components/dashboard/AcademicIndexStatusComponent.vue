<template>
  <a-card title="Academic GraphRAG Index" :loading="loading" class="dashboard-card index-status-card">
    <template #extra>
      <div class="header-extra">
        <div class="service-pills">
          <div v-for="service in services" :key="service.key" class="service-pill" :class="service.status">
            <span class="status-dot" :class="service.status" />
            <span class="service-name">{{ service.shortLabel }}</span>
          </div>
        </div>
        <a-tooltip title="Refresh index statistics">
          <button class="icon-button" type="button" :disabled="loading" @click="$emit('refresh')">
            <RefreshCw :class="{ spinning: loading }" />
          </button>
        </a-tooltip>
      </div>
    </template>

    <!-- Top 3 Key Metrics Summary -->
    <div class="index-summary">
      <div class="summary-item entities">
        <Boxes class="summary-icon" />
        <div class="summary-content">
          <div class="summary-value">{{ formatNumber(stats.kg_nodes_count) }}</div>
          <div class="summary-label">Graph Entities</div>
        </div>
      </div>
      <div class="summary-item relationships">
        <Share2 class="summary-icon" />
        <div class="summary-content">
          <div class="summary-value">{{ formatNumber(stats.kg_edges_count) }}</div>
          <div class="summary-label">Graph Relationships</div>
        </div>
      </div>
      <div class="summary-item vectors">
        <Database class="summary-icon" />
        <div class="summary-content">
          <div class="summary-value">{{ formatNumber(stats.vector_records_count) }}</div>
          <div class="summary-label">Vector Records</div>
        </div>
      </div>
    </div>

    <a-divider style="margin: 16px 0;" />

    <!-- Distribution Grid -->
    <div class="distribution-grid">
      <div class="distribution-section">
        <div class="section-title">Entity Distribution</div>
        <DistributionRows :items="entityItems" empty-label="No graph entities indexed" type="entity" />
      </div>
      <div class="distribution-section">
        <div class="section-title">Relationship Distribution</div>
        <DistributionRows :items="relationshipItems" empty-label="No graph relationships indexed" type="relationship" />
      </div>
      <div class="distribution-section">
        <div class="section-title">Vector Collections</div>
        <DistributionRows :items="collectionItems" empty-label="No vector records indexed" type="vector" />
      </div>
    </div>
  </a-card>
</template>

<script setup>
import { computed, defineComponent, h } from 'vue'
import { Boxes, Database, RefreshCw, Share2 } from 'lucide-vue-next'

const props = defineProps({
  academicStats: {
    type: Object,
    default: () => ({})
  },
  loading: {
    type: Boolean,
    default: false
  }
})

defineEmits(['refresh'])

const stats = computed(() => props.academicStats || {})
const formatNumber = (value) => new Intl.NumberFormat('en-US').format(Number(value || 0))

const distributionItems = (values = {}) =>
  Object.entries(values)
    .map(([label, value]) => ({ label, value: Number(value || 0) }))
    .filter((item) => item.value > 0)
    .sort((left, right) => right.value - left.value)
    .slice(0, 10)

const entityItems = computed(() => distributionItems(stats.value.graph_entity_distribution))
const relationshipItems = computed(() =>
  distributionItems(stats.value.graph_relationship_distribution)
)
const collectionItems = computed(() => distributionItems(stats.value.vector_collections))

const services = computed(() =>
  [
    ['supabase', 'PostgreSQL'],
    ['neo4j', 'Neo4j'],
    ['milvus', 'Milvus']
  ].map(([key, shortLabel]) => {
    const source = stats.value.source_status?.[key] || {}
    return {
      key,
      shortLabel,
      status: source.status || 'ready'
    }
  })
)

// Thematic colors matching Yuxi dark mode palette
const getBarColor = (label, type) => {
  if (type === 'entity') {
    const entityColors = {
      Concept: '#a855f7',
      Keyword: '#06b6d4',
      Publication: '#10b981',
      Venue: '#ec4899',
      Lecturer: '#f59e0b',
      Year: '#d97706',
      Institution: '#3b82f6'
    }
    return entityColors[label] || '#38bdf8'
  }
  if (type === 'relationship') {
    const relColors = {
      HAS_TOPIC: '#38bdf8',
      HAS_KEYWORD: '#818cf8',
      USES_METHOD: '#c084fc',
      PUBLISHES: '#34d399',
      HAS_AUTHOR: '#fbbf24',
      PUBLISHED_IN_YEAR: '#f43f5e',
      PUBLISHED_IN_VENUE: '#f472b6'
    }
    return relColors[label] || '#38bdf8'
  }
  // Vector collections
  return '#38bdf8'
}

const DistributionRows = defineComponent({
  props: {
    items: {
      type: Array,
      default: () => []
    },
    emptyLabel: {
      type: String,
      required: true
    },
    type: {
      type: String,
      default: 'entity'
    }
  },
  setup(componentProps) {
    return () => {
      if (!componentProps.items.length) {
        return h('div', { class: 'empty-distribution' }, componentProps.emptyLabel)
      }
      const maxValue = Math.max(...componentProps.items.map((item) => item.value), 1)
      return h(
        'div',
        { class: 'distribution-rows' },
        componentProps.items.map((item) => {
          const color = getBarColor(item.label, componentProps.type)
          return h('div', { class: 'distribution-row', key: item.label }, [
            h('div', { class: 'distribution-label' }, [
              h('span', { title: item.label, class: 'item-name' }, item.label),
              h('strong', { class: 'item-value' }, formatNumber(item.value))
            ]),
            h('div', { class: 'bar-track' }, [
              h('div', {
                class: 'bar-fill',
                style: {
                  width: `${Math.max(3, (item.value / maxValue) * 100)}%`,
                  backgroundColor: color
                }
              })
            ])
          ])
        })
      )
    }
  }
})
</script>

<style scoped lang="less">
.index-status-card {
  height: 100%;

  :deep(.ant-card-head) {
    min-height: 48px;
    padding: 0 16px;
    .ant-card-head-title {
      font-size: 15px;
      font-weight: 600;
    }
  }

  :deep(.ant-card-body) {
    padding: 16px;
  }
}

.header-extra {
  display: flex;
  align-items: center;
  gap: 12px;
}

.service-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

.service-pill {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 12px;
  background: var(--gray-100, rgba(255, 255, 255, 0.05));
  border: 1px solid var(--gray-200, rgba(255, 255, 255, 0.1));

  .service-name {
    font-size: 11px;
    font-weight: 600;
    color: var(--gray-700);
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;

    &.ready {
      background: #34d399;
      box-shadow: 0 0 6px rgba(52, 211, 153, 0.4);
    }
    &.error {
      background: #f87171;
    }
    &.unconfigured {
      background: #94a3b8;
    }
  }
}

.icon-button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--gray-200, rgba(255, 255, 255, 0.1));
  border-radius: 6px;
  color: var(--gray-600);
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;

  &:hover:not(:disabled) {
    border-color: #38bdf8;
    color: #38bdf8;
  }

  &:disabled {
    cursor: wait;
    opacity: 0.55;
  }

  svg {
    width: 15px;
    height: 15px;
  }
}

.spinning {
  animation: spin 1s linear infinite;
}

.index-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;

  .summary-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-radius: 8px;
    background: var(--gray-50, rgba(255, 255, 255, 0.02));
    border: 1px solid var(--gray-150, rgba(255, 255, 255, 0.05));

    .summary-icon {
      width: 24px;
      height: 24px;
      flex-shrink: 0;
    }

    &.entities .summary-icon {
      color: #a855f7;
    }
    &.relationships .summary-icon {
      color: #38bdf8;
    }
    &.vectors .summary-icon {
      color: #34d399;
    }

    .summary-value {
      font-size: 20px;
      font-weight: 700;
      line-height: 1.2;
      color: var(--gray-1000, #f8fafc);
    }

    .summary-label {
      font-size: 11px;
      font-weight: 500;
      color: var(--gray-500);
    }
  }
}

.distribution-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}

.distribution-section {
  min-width: 0;

  .section-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--gray-600);
    margin-bottom: 10px;
  }
}

:deep(.distribution-rows) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.distribution-row) {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

:deep(.distribution-label) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;

  .item-name {
    color: var(--gray-600);
    font-family: monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .item-value {
    color: var(--gray-800, #f8fafc);
    font-weight: 600;
  }
}

:deep(.bar-track) {
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: var(--gray-100, rgba(255, 255, 255, 0.08));
}

:deep(.bar-fill) {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

:deep(.empty-distribution) {
  padding: 16px 0;
  color: var(--gray-400);
  font-size: 12px;
  text-align: center;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .index-summary,
  .distribution-grid {
    grid-template-columns: 1fr;
  }
}
</style>
