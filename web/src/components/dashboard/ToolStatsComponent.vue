<template>
  <a-card title="Tool Call Monitoring" :loading="loading" class="dashboard-card tool-stats-card">
    <!-- Tool call overview metrics -->
    <div class="stats-overview">
      <div class="stat-box">
        <div class="stat-title">TOTAL CALLS</div>
        <div class="stat-value total-calls">{{ toolStats?.total_calls || 0 }}</div>
      </div>
      <div class="stat-box">
        <div class="stat-title">FAILED CALLS</div>
        <div class="stat-value failed-calls">
          {{ toolStats?.failed_calls || 0 }} <span class="unit">times</span>
        </div>
      </div>
      <div class="stat-box">
        <div class="stat-title">SUCCESS RATE</div>
        <div class="stat-value success-rate" :class="getSuccessRateClass(toolStats?.success_rate)">
          {{ toolStats?.success_rate ?? 100 }}<span class="unit">%</span>
        </div>
      </div>
    </div>

    <!-- Most used tools chart -->
    <div class="chart-section">
      <div class="chart-title">Top 10 Most Used Tools</div>
      <div ref="toolsChartRef" class="chart-container"></div>
    </div>

    <!-- Error analysis section if errors exist -->
    <div class="error-analysis" v-if="hasErrorData">
      <div class="chart-title">Tool Error Analysis</div>
      <a-row :gutter="16">
        <a-col :span="12">
          <a-table
            :columns="errorColumns"
            :data-source="errorData"
            size="small"
            :pagination="false"
            :scroll="{ y: 160 }"
            class="error-table"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'tool_name'">
                <span class="tool-tag">{{ record.tool_name }}</span>
              </template>
              <template v-if="column.key === 'error_count'">
                <a-tag :color="record.error_count > 5 ? 'red' : 'orange'">
                  {{ record.error_count }}
                </a-tag>
              </template>
            </template>
          </a-table>
        </a-col>
        <a-col :span="12">
          <div ref="errorChartRef" class="chart-small"></div>
        </a-col>
      </a-row>
    </div>
  </a-card>
</template>

<script setup>
import { ref, onMounted, watch, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()

const props = defineProps({
  toolStats: {
    type: Object,
    default: () => ({})
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const toolsChartRef = ref(null)
const errorChartRef = ref(null)
let toolsChart = null
let errorChart = null

const errorColumns = [
  {
    title: 'Tool Name',
    dataIndex: 'tool_name',
    key: 'tool_name',
    width: '60%'
  },
  {
    title: 'Error Count',
    dataIndex: 'error_count',
    key: 'error_count',
    width: '40%',
    sorter: (a, b) => a.error_count - b.error_count
  }
]

const hasErrorData = computed(() => {
  return (
    props.toolStats?.tool_error_distribution &&
    Object.keys(props.toolStats.tool_error_distribution).length > 0
  )
})

const errorData = computed(() => {
  if (!hasErrorData.value) return []
  return Object.entries(props.toolStats.tool_error_distribution)
    .map(([tool_name, error_count]) => ({ tool_name, error_count }))
    .sort((a, b) => b.error_count - a.error_count)
})

const getSuccessRateClass = (rate) => {
  const val = rate ?? 100
  if (val >= 90) return 'rate-high'
  if (val >= 70) return 'rate-mid'
  return 'rate-low'
}

const initToolsChart = () => {
  if (!toolsChartRef.value || !props.toolStats?.most_used_tools?.length) return

  if (toolsChart) {
    toolsChart.dispose()
    toolsChart = null
  }

  toolsChart = echarts.init(toolsChartRef.value)

  const isDark = themeStore.isDark
  const textColor = isDark ? '#94a3b8' : '#64748b'
  const gridLineColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)'
  const tooltipBg = isDark ? '#0f172a' : '#ffffff'
  const tooltipBorder = isDark ? '#1e293b' : '#e2e8f0'
  const tooltipText = isDark ? '#f8fafc' : '#0f172a'

  // Top 10 items sorted ascending for horizontal bar chart
  const data = [...props.toolStats.most_used_tools].sort((a, b) => a.count - b.count).slice(0, 10)

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      borderWidth: 1,
      textStyle: { color: tooltipText, fontSize: 12 },
      formatter: '{b}: <b>{c} calls</b>'
    },
    grid: {
      left: '3%',
      right: '6%',
      bottom: '3%',
      top: '4%',
      containLabel: true
    },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: textColor, fontSize: 11 },
      splitLine: { lineStyle: { color: gridLineColor, type: 'dashed' } }
    },
    yAxis: {
      type: 'category',
      data: data.map((item) => item.tool_name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: textColor,
        fontSize: 11.5,
        fontFamily: 'monospace',
        interval: 0
      }
    },
    series: [
      {
        name: 'Calls',
        type: 'bar',
        barWidth: 14,
        data: data.map((item) => item.count),
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#0284c7' },
            { offset: 1, color: '#38bdf8' }
          ])
        },
        emphasis: {
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: '#0369a1' },
              { offset: 1, color: '#7dd3fc' }
            ])
          }
        }
      }
    ]
  }

  toolsChart.setOption(option)
}

const initErrorChart = () => {
  if (!errorChartRef.value || !hasErrorData.value) return

  if (errorChart) {
    errorChart.dispose()
    errorChart = null
  }

  errorChart = echarts.init(errorChartRef.value)
  const isDark = themeStore.isDark

  const data = errorData.value.slice(0, 5)

  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: isDark ? '#0f172a' : '#ffffff',
      borderColor: isDark ? '#1e293b' : '#e2e8f0',
      textStyle: { color: isDark ? '#f8fafc' : '#0f172a' },
      formatter: '{b}: {c} ({d}%)'
    },
    series: [
      {
        name: 'Errors',
        type: 'pie',
        radius: ['35%', '65%'],
        center: ['50%', '50%'],
        data: data.map((item) => ({
          name: item.tool_name,
          value: item.error_count
        })),
        itemStyle: {
          borderRadius: 4,
          borderColor: isDark ? '#1e293b' : '#ffffff',
          borderWidth: 2
        },
        label: { show: false }
      }
    ]
  }

  errorChart.setOption(option)
}

const updateCharts = () => {
  nextTick(() => {
    initToolsChart()
    if (hasErrorData.value) {
      initErrorChart()
    }
  })
}

watch(
  () => props.toolStats,
  () => updateCharts(),
  { deep: true }
)

watch(
  () => themeStore.isDark,
  () => updateCharts()
)

const handleResize = () => {
  if (toolsChart) toolsChart.resize()
  if (errorChart) errorChart.resize()
}

onMounted(() => {
  updateCharts()
  window.addEventListener('resize', handleResize)
})

const cleanup = () => {
  window.removeEventListener('resize', handleResize)
  if (toolsChart) {
    toolsChart.dispose()
    toolsChart = null
  }
  if (errorChart) {
    errorChart.dispose()
    errorChart = null
  }
}

defineExpose({ cleanup })
</script>

<style scoped lang="less">
.tool-stats-card {
  height: 100%;
  display: flex;
  flex-direction: column;

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
    display: flex;
    flex-direction: column;
    flex: 1;

    /* High-contrast background in Dark Mode for card body */
    .dashboard-container & {
      background-color: var(--gray-0);
    }
  }
}

.stats-overview {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;

  .stat-box {
    display: flex;
    flex-direction: column;
    gap: 4px;

    .stat-title {
      font-size: 11px;
      font-weight: 600;
      color: var(--gray-500);
      letter-spacing: 0.5px;
    }

    .stat-value {
      font-size: 22px;
      font-weight: 700;
      line-height: 1.2;

      .unit {
        font-size: 12px;
        font-weight: 500;
        margin-left: 2px;
      }

      &.total-calls {
        color: #38bdf8;
      }

      &.failed-calls {
        color: #f87171;
      }

      &.rate-high {
        color: #34d399;
      }

      &.rate-mid {
        color: #fbbf24;
      }

      &.rate-low {
        color: #f87171;
      }
    }
  }
}

.chart-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 220px;

  .chart-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--gray-600);
    margin-bottom: 8px;
  }

  .chart-container {
    width: 100%;
    height: 230px;
  }
}

.error-analysis {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-200);

  .chart-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--gray-600);
    margin-bottom: 8px;
  }

  .tool-tag {
    font-family: monospace;
    font-size: 11px;
    color: #38bdf8;
  }

  .chart-small {
    width: 100%;
    height: 160px;
  }
}
</style>
