<template>
  <section class="index-status">
    <header class="index-header">
      <div>
        <div class="title-row">
          <Network class="title-icon" />
          <h3>Academic GraphRAG Index</h3>
        </div>
        <div class="index-meta">
          <span>{{ stats.graph_name || 'yunesa_academic_kg' }}</span>
          <span>{{ stats.embedding_model || 'Embedding model unavailable' }}</span>
          <span v-if="stats.embedding_dimension">{{ stats.embedding_dimension }} dimensions</span>
        </div>
      </div>
      <a-tooltip title="Refresh index statistics">
        <button class="icon-button" type="button" :disabled="loading" @click="$emit('refresh')">
          <RefreshCw :class="{ spinning: loading }" />
        </button>
      </a-tooltip>
    </header>

    <div class="service-row">
      <div v-for="service in services" :key="service.key" class="service-status">
        <span class="status-dot" :class="service.status" />
        <span class="service-name">{{ service.label }}</span>
        <span class="service-detail">{{ service.detail }}</span>
      </div>
    </div>

    <div class="index-summary">
      <div class="summary-item">
        <Boxes />
        <strong>{{ formatNumber(stats.kg_nodes_count) }}</strong>
        <span>Graph entities</span>
      </div>
      <div class="summary-item">
        <Share2 />
        <strong>{{ formatNumber(stats.kg_edges_count) }}</strong>
        <span>Graph relationships</span>
      </div>
      <div class="summary-item">
        <Database />
        <strong>{{ formatNumber(stats.vector_records_count) }}</strong>
        <span>Vector records</span>
      </div>
    </div>

    <div class="distribution-grid">
      <div class="distribution-section">
        <h4>Entity Distribution</h4>
        <DistributionRows :items="entityItems" empty-label="No graph entities indexed" />
      </div>
      <div class="distribution-section">
        <h4>Relationship Distribution</h4>
        <DistributionRows :items="relationshipItems" empty-label="No graph relationships indexed" />
      </div>
      <div class="distribution-section">
        <h4>Vector Collections</h4>
        <DistributionRows :items="collectionItems" empty-label="No vector records indexed" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, defineComponent, h } from 'vue'
import { Boxes, Database, Network, RefreshCw, Share2 } from 'lucide-vue-next'

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
    ['supabase', 'PostgreSQL (Self-Hosted)'],
    ['neo4j', 'Neo4j (Self-Hosted)'],
    ['milvus', 'Milvus (Self-Hosted)']
  ].map(([key, label]) => {
    const source = stats.value.source_status?.[key] || {}
    return {
      key,
      label,
      status: source.status || 'unconfigured',
      detail: source.detail || 'Status unavailable'
    }
  })
)

const DistributionRows = defineComponent({
  props: {
    items: {
      type: Array,
      default: () => []
    },
    emptyLabel: {
      type: String,
      required: true
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
        componentProps.items.map((item) =>
          h('div', { class: 'distribution-row', key: item.label }, [
            h('div', { class: 'distribution-label' }, [
              h('span', { title: item.label }, item.label),
              h('strong', formatNumber(item.value))
            ]),
            h('div', { class: 'bar-track' }, [
              h('div', {
                class: 'bar-fill',
                style: { width: `${Math.max(3, (item.value / maxValue) * 100)}%` }
              })
            ])
          ])
        )
      )
    }
  }
})
</script>

<style scoped lang="less">
.index-status {
  height: 100%;
  padding: 22px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--bg-sider);
}

.index-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 9px;

  h3 {
    margin: 0;
    color: var(--gray-1000);
    font-size: 16px;
    font-weight: 600;
  }
}

.title-icon {
  width: 20px;
  height: 20px;
  color: var(--main-color);
}

.index-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 7px;
  color: var(--gray-500);
  font-size: 12px;
}

.icon-button {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  color: var(--gray-600);
  background: transparent;
  cursor: pointer;

  &:hover:not(:disabled) {
    border-color: var(--main-color);
    color: var(--main-color);
  }

  &:disabled {
    cursor: wait;
    opacity: 0.55;
  }

  svg {
    width: 17px;
    height: 17px;
  }
}

.spinning {
  animation: spin 1s linear infinite;
}

.service-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.service-status {
  display: grid;
  grid-template-columns: 9px auto 1fr;
  align-items: center;
  min-width: 0;
  gap: 7px;
  padding: 9px 10px;
  border-top: 1px solid var(--gray-150);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--gray-400);

  &.ready {
    background: var(--color-success-600);
  }

  &.error {
    background: var(--color-error-600);
  }

  &.empty {
    background: var(--color-warning-600);
  }
}

.service-name {
  color: var(--gray-900);
  font-size: 12px;
  font-weight: 600;
}

.service-detail {
  overflow: hidden;
  color: var(--gray-500);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.index-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin: 18px 0 22px;
  padding: 16px 0;
  border-top: 1px solid var(--gray-150);
  border-bottom: 1px solid var(--gray-150);
}

.summary-item {
  display: grid;
  grid-template-columns: 22px auto;
  align-items: center;
  gap: 2px 10px;

  svg {
    grid-row: 1 / 3;
    width: 19px;
    height: 19px;
    color: var(--main-color);
  }

  strong {
    color: var(--gray-1000);
    font-size: 20px;
    line-height: 1.2;
  }

  span {
    color: var(--gray-500);
    font-size: 11px;
  }
}

.distribution-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 24px;
}

.distribution-section {
  min-width: 0;

  h4 {
    margin: 0 0 12px;
    color: var(--gray-900);
    font-size: 13px;
    font-weight: 600;
  }
}

:deep(.distribution-rows) {
  display: grid;
  gap: 10px;
}

:deep(.distribution-label) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: 10px;
  margin-bottom: 4px;
  color: var(--gray-600);
  font-size: 11px;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: var(--gray-800);
    font-weight: 600;
  }
}

:deep(.bar-track) {
  height: 5px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--gray-100);
}

:deep(.bar-fill) {
  height: 100%;
  border-radius: 2px;
  background: var(--main-color);
}

:deep(.empty-distribution) {
  padding: 24px 0;
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
  .service-row,
  .index-summary,
  .distribution-grid {
    grid-template-columns: 1fr;
  }
}
</style>
