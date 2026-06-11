<template>
  <a-card title="Academic Corpus" :loading="loading" class="dashboard-card">
    <div class="corpus-header">
      <div class="corpus-metrics">
        <div class="metric">
          <BookOpen class="metric-icon publications" />
          <div>
            <div class="metric-value">{{ formatNumber(stats.papers_count) }}</div>
            <div class="metric-label">Publications</div>
          </div>
        </div>
        <div class="metric">
          <GraduationCap class="metric-icon lecturers" />
          <div>
            <div class="metric-value">{{ formatNumber(stats.lecturers_count) }}</div>
            <div class="metric-label">Lecturers</div>
          </div>
        </div>
        <div class="metric">
          <Link2 class="metric-icon authorship" />
          <div>
            <div class="metric-value">{{ formatNumber(stats.authorship_links_count) }}</div>
            <div class="metric-label">Authorship Links</div>
          </div>
        </div>
      </div>
      <a-tag :color="statusColor">{{ statusLabel }}</a-tag>
    </div>

    <a-divider />

    <div class="completeness-list">
      <div v-for="item in completeness" :key="item.key" class="completeness-item">
        <div class="completeness-label">
          <component :is="item.icon" class="field-icon" />
          <span>{{ item.label }}</span>
          <strong>{{ formatNumber(item.count) }}/{{ formatNumber(stats.papers_count) }}</strong>
        </div>
        <a-progress
          :percent="item.percent"
          :show-info="true"
          :stroke-color="item.color"
          size="small"
        />
      </div>
    </div>
  </a-card>
</template>

<script setup>
import { computed } from 'vue'
import { BookOpen, FileText, GraduationCap, Link2, Sparkles, Tags } from 'lucide-vue-next'

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

const stats = computed(() => props.academicStats || {})
const sourceStatus = computed(() => stats.value.source_status?.supabase?.status || 'unconfigured')
const statusLabel = computed(
  () =>
    ({
      ready: 'Connected',
      error: 'Unavailable',
      unconfigured: 'Not configured',
      empty: 'No data'
    })[sourceStatus.value] || 'Unknown'
)
const statusColor = computed(
  () =>
    ({
      ready: 'success',
      error: 'error',
      unconfigured: 'default',
      empty: 'warning'
    })[sourceStatus.value] || 'default'
)

const percentage = (count) => {
  const total = Number(stats.value.papers_count || 0)
  return total > 0 ? Math.round((Number(count || 0) / total) * 100) : 0
}

const completeness = computed(() => [
  {
    key: 'abstract',
    label: 'Abstract',
    count: stats.value.papers_with_abstract || 0,
    percent: percentage(stats.value.papers_with_abstract),
    icon: FileText,
    color: 'var(--main-color)'
  },
  {
    key: 'keywords',
    label: 'Keywords',
    count: stats.value.papers_with_keywords || 0,
    percent: percentage(stats.value.papers_with_keywords),
    icon: Tags,
    color: 'var(--color-success-600)'
  },
  {
    key: 'tldr',
    label: 'KG-oriented TLDR',
    count: stats.value.papers_with_tldr || 0,
    percent: percentage(stats.value.papers_with_tldr),
    icon: Sparkles,
    color: 'var(--color-warning-600)'
  }
])

const formatNumber = (value) => new Intl.NumberFormat('en-US').format(Number(value || 0))
</script>

<style scoped lang="less">
.corpus-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.corpus-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
  gap: 18px;
}

.metric {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 10px;
}

.metric-icon {
  width: 20px;
  height: 20px;
  flex: 0 0 auto;

  &.publications {
    color: var(--main-color);
  }

  &.lecturers {
    color: var(--color-success-700);
  }

  &.authorship {
    color: var(--color-warning-700);
  }
}

.metric-value {
  color: var(--gray-1000);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.metric-label {
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.4;
}

.completeness-list {
  display: grid;
  gap: 14px;
}

.completeness-label {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  align-items: center;
  gap: 8px;
  margin-bottom: 5px;
  color: var(--gray-700);
  font-size: 12px;

  strong {
    color: var(--gray-900);
    font-weight: 600;
  }
}

.field-icon {
  width: 16px;
  height: 16px;
  color: var(--gray-500);
}

@media (max-width: 768px) {
  .corpus-header {
    flex-direction: column;
  }

  .corpus-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
