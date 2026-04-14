<template>
  <a-card title="Knowledge Base Usage" :loading="loading" class="dashboard-card">
    <!-- Knowledge base overview -->
    <div class="stats-overview">
      <a-row :gutter="16">
        <a-col :span="8">
          <a-statistic
            title="Total Knowledge Bases"
            :value="knowledgeStats?.total_databases || 0"
            :value-style="{ color: 'var(--color-info-500)' }"
            suffix="items"
          />
        </a-col>
        <a-col :span="8">
          <a-statistic
            title="Total Files"
            :value="knowledgeStats?.total_files || 0"
            :value-style="{ color: 'var(--color-success-500)' }"
            suffix="items"
          />
        </a-col>
        <a-col :span="8">
          <a-statistic
            title="Storage Size"
            :value="formattedStorageSize"
            :value-style="{ color: 'var(--color-warning-500)' }"
          />
        </a-col>
      </a-row>
    </div>

    <a-divider />

    <!-- Chart area: split into two rows -->
    <a-row :gutter="24" style="margin-bottom: 16px">
      <!-- Database type distribution -->
      <a-col :span="24">
        <div class="chart-container">
          <div class="chart-header">
            <h4>Type Distribution</h4>
            <div class="legend" v-if="dbTypeLegend.length">
              <div class="legend-item" v-for="(item, idx) in dbTypeLegend" :key="item.name">
                <span
                  class="legend-color"
                  :style="{ backgroundColor: getLegendColorByIndex(idx) }"
                ></span>
                <span class="legend-label">{{ item.name }}</span>
              </div>
            </div>
          </div>
          <div ref="dbTypeChartRef" class="chart chart--thin"></div>
        </div>
      </a-col>
    </a-row>

    <a-row :gutter="24">
      <!-- File type distribution -->
      <a-col :span="24">
        <div class="chart-container">
          <h4>File Type Distribution</h4>
          <div ref="fileTypeChartRef" class="chart donut-chart-container">
            <div class="carousel-info" v-if="fileTypeData.length > 0">
              <div
                class="carousel-item"
                :class="{ active: currentCarouselIndex === index }"
                v-for="(item, index) in fileTypeData"
                :key="item.name"
              >
                <div class="carousel-label">{{ item.name }}</div>
                <div class="carousel-value">{{ item.value }}</div>
                <div class="carousel-percent">
                  {{ ((item.value / totalFiles) * 100).toFixed(1) }}%
                </div>
              </div>
            </div>
          </div>
        </div>
      </a-col>
    </a-row>

    <!-- Detailed statistics -->
    <!-- <a-divider />
    <a-row :gutter="16">
      <a-col :span="8">
        <a-statistic
          title="Average files per database"
          :value="averageFilesPerDatabase"
          suffix="items"
          :precision="1"
        />
      </a-col>
      <a-col :span="8">
        <a-statistic
          title="Average nodes per file"
          :value="averageNodesPerFile"
          suffix="items"
          :precision="1"
        />
      </a-col>
      <a-col :span="8">
        <a-statistic
          title="Average node size"
          :value="averageNodeSize"
          suffix="KB"
          :precision="2"
        />
      </a-col>
    </a-row> -->
  </a-card>
</template>

<script setup>
import { ref, onMounted, watch, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import { getColorByIndex, getColorPalette } from '@/utils/chartColors'
import { useThemeStore } from '@/stores/theme'

// CSS variable parsing helper
function getCSSVariable(variableName, element = document.documentElement) {
  return getComputedStyle(element).getPropertyValue(variableName).trim()
}

// theme store
const themeStore = useThemeStore()

// Props
const props = defineProps({
  knowledgeStats: {
    type: Object,
    default: () => ({})
  },
  loading: {
    type: Boolean,
    default: false
  }
})

// Chart refs
const dbTypeChartRef = ref(null)
const fileTypeChartRef = ref(null)
let dbTypeChart = null
let fileTypeChart = null

// File type chart data for carousel
const fileTypeData = ref([])
const totalFiles = ref(0)
const currentCarouselIndex = ref(0)
let carouselTimer = null

// Computed properties
const formattedStorageSize = computed(() => {
  const size = props.knowledgeStats?.total_storage_size || 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(2)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(2)} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`
})

// const averageFilesPerDatabase = computed(() => {
//   const databases = props.knowledgeStats?.total_databases || 0
//   const files = props.knowledgeStats?.total_files || 0
//   return databases > 0 ? files / databases : 0
// })

// const averageNodeSize = computed(() => {
//   const nodes = props.knowledgeStats?.total_nodes || 0
//   const size = props.knowledgeStats?.total_storage_size || 0
//   return nodes > 0 ? size / (nodes * 1024) : 0 // Convert to KB
// })

// Use unified color palette
const getLegendColorByIndex = (index) => getColorByIndex(index)

// Initialize database type distribution chart - horizontal segmented bar
const dbTypeLegend = ref([])
const initDbTypeChart = () => {
  if (!dbTypeChartRef.value || !props.knowledgeStats?.databases_by_type) return

  const entries = Object.entries(props.knowledgeStats.databases_by_type)
    .map(([type, count]) => ({ name: type || 'Unknown', value: count }))
    .filter((item) => item.value > 0)

  // update legend data
  dbTypeLegend.value = entries

  if (!dbTypeChart) {
    dbTypeChart = echarts.init(dbTypeChartRef.value)
  }

  const total = entries.reduce((sum, item) => sum + item.value, 0)

  // Build stacked bar series, but render with neutral color and separators
  const series = entries.map((item, idx) => ({
    name: item.name,
    type: 'bar',
    stack: 'total',
    barWidth: 28,
    data: [item.value],
    itemStyle: {
      color: getLegendColorByIndex(idx),
      borderColor: getCSSVariable('--gray-0'),
      borderWidth: 2,
      borderJoin: 'miter'
    },
    emphasis: {
      itemStyle: {
        color: getLegendColorByIndex(idx)
      }
    }
  }))

  const option = {
    animation: false,
    tooltip: {
      trigger: 'item',
      backgroundColor: getCSSVariable('--gray-0'),
      borderColor: getCSSVariable('--gray-200'),
      borderWidth: 1,
      textStyle: { color: getCSSVariable('--gray-600') },
      formatter: (params) => {
        const value = params.value || 0
        return `${params.seriesName}: ${value}/${total}`
      }
    },
    grid: { left: 0, right: 0, top: 10, bottom: 10, containLabel: false },
    xAxis: {
      type: 'value',
      show: false,
      max: total > 0 ? total : undefined
    },
    yAxis: {
      type: 'category',
      show: false,
      data: ['all']
    },
    series
  }

  dbTypeChart.setOption(option, true)
}

// Initialize file type distribution chart
const initFileTypeChart = () => {
  if (!fileTypeChartRef.value) return

  // Destroy existing chart instance first if it exists.
  if (fileTypeChart) {
    fileTypeChart.dispose()
    fileTypeChart = null
  }

  fileTypeChart = echarts.init(fileTypeChartRef.value)

  // Check whether file-type data exists - compatible with old and new field names.
  const fileTypesData =
    props.knowledgeStats?.files_by_type || props.knowledgeStats?.file_type_distribution || {}
  if (Object.keys(fileTypesData).length > 0) {
    const data = Object.entries(fileTypesData)
      .map(([type, count]) => ({
        name: type || 'Unknown',
        value: count
      }))
      .sort((a, b) => b.value - a.value) // Sort by count

    // Set carousel data
    fileTypeData.value = data
    totalFiles.value = data.reduce((sum, item) => sum + item.value, 0)

    // Start carousel
    startCarousel()

    const option = {
      tooltip: {
        trigger: 'item',
        backgroundColor: getCSSVariable('--gray-0'),
        borderColor: getCSSVariable('--gray-200'),
        borderWidth: 1,
        textStyle: {
          color: getCSSVariable('--gray-600')
        },
        formatter: '{a} <br/>{b}: {c} ({d}%)'
      },
      legend: {
        orient: 'horizontal',
        bottom: '5%',
        left: 'center',
        itemGap: 16,
        itemWidth: 10,
        itemHeight: 10,
        textStyle: {
          fontSize: 11,
          color: getCSSVariable('--gray-600')
        }
      },
      series: [
        {
          name: 'File Types',
          type: 'pie',
          radius: ['45%', '75%'], // Use a larger ring to leave more center space
          center: ['50%', '45%'], // Move upward to make room for center + bottom legend
          avoidLabelOverlap: true, // Avoid label overlap
          itemStyle: {
            borderRadius: 8,
            borderColor: getCSSVariable('--gray-0'),
            borderWidth: 2
          },
          label: {
            show: false // Hide labels on pie chart, use legend instead
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: getCSSVariable('--shadow-3')
            }
          },
          labelLine: {
            show: false // Hide label lines
          },
          data: data,
          color: getColorPalette()
        }
      ]
    }

    fileTypeChart.setOption(option)
  } else {
    // Clear carousel data
    fileTypeData.value = []
    totalFiles.value = 0
    stopCarousel()

    // If no file-type data exists, show a placeholder chart.
    const option = {
      tooltip: {
        trigger: 'item',
        backgroundColor: getCSSVariable('--gray-0'),
        borderColor: getCSSVariable('--gray-200'),
        borderWidth: 1,
        textStyle: {
          color: getCSSVariable('--gray-600')
        },
        formatter: '{a} <br/>{b}: {c} ({d}%)'
      },
      series: [
        {
          name: 'File Types',
          type: 'pie',
          radius: ['45%', '75%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 8,
            borderColor: getCSSVariable('--gray-0'),
            borderWidth: 2
          },
          label: {
            show: false
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: getCSSVariable('--shadow-3')
            }
          },
          labelLine: {
            show: false
          },
          data: [{ name: 'No Data', value: 1 }],
          color: [getCSSVariable('--color-info-500')]
        }
      ]
    }

    fileTypeChart.setOption(option)
  }
}

// Carousel behavior
const startCarousel = () => {
  stopCarousel() // Stop previous carousel first.
  if (fileTypeData.value.length <= 1) return

  // Reset index
  currentCarouselIndex.value = 0

  // Start new carousel and switch every 3 seconds.
  carouselTimer = setInterval(() => {
    currentCarouselIndex.value = (currentCarouselIndex.value + 1) % fileTypeData.value.length
  }, 3000)
}

const stopCarousel = () => {
  if (carouselTimer) {
    clearInterval(carouselTimer)
    carouselTimer = null
  }
}

// Update charts
const updateCharts = () => {
  nextTick(() => {
    initDbTypeChart()
    initFileTypeChart()
  })
}

// Watch data changes
watch(
  () => props.knowledgeStats,
  () => {
    updateCharts()
  },
  { deep: true }
)

// Resize charts on window size changes
const handleResize = () => {
  if (dbTypeChart) dbTypeChart.resize()
  if (fileTypeChart) fileTypeChart.resize()
}

onMounted(() => {
  updateCharts()
  window.addEventListener('resize', handleResize)
})

// Watch theme changes and re-render charts
watch(
  () => themeStore.isDark,
  () => {
    if (props.knowledgeStats && (dbTypeChart || fileTypeChart)) {
      nextTick(() => {
        updateCharts()
      })
    }
  }
)

// Cleanup on component unmount
const cleanup = () => {
  window.removeEventListener('resize', handleResize)
  stopCarousel() // Stop carousel
  if (dbTypeChart) {
    dbTypeChart.dispose()
    dbTypeChart = null
  }
  if (fileTypeChart) {
    fileTypeChart.dispose()
    fileTypeChart = null
  }
}

// Expose cleanup function for parent component
defineExpose({
  cleanup
})
</script>

<style scoped lang="less">
// KnowledgeStatsComponent specific styles
.chart-container {
  .chart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;

    h4 {
      margin: 0;
    }

    .legend {
      display: flex;
      gap: 12px;
      align-items: center;

      .legend-item {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--gray-500);
      }

      .legend-color {
        width: 10px;
        height: 10px;
        border-radius: 2px;
      }
    }
  }

  .chart {
    height: 300px;
    width: 100%;
  }

  .chart--thin {
    height: 80px;
  }

  // Donut chart container styles
  .donut-chart-container {
    position: relative;

    .carousel-info {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      text-align: center;
      pointer-events: none;
      z-index: 10;

      .carousel-item {
        opacity: 0;
        transition: opacity 0.5s ease-in-out;
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        white-space: nowrap;

        &.active {
          opacity: 1;
        }

        .carousel-label {
          font-size: 14px;
          font-weight: 600;
          color: var(--gray-500);
          margin-bottom: 4px;
        }

        .carousel-value {
          font-size: 24px;
          font-weight: 700;
          color: var(--gray-800);
          margin-bottom: 2px;
          line-height: 1;
        }

        .carousel-percent {
          font-size: 12px;
          color: var(--gray-400);
          font-weight: 500;
        }
      }
    }
  }
}
</style>
