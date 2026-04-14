<template>
  <div class="rag-evaluation-container">
    <!-- Top toolbar -->
    <div class="toolbar">
      <div class="toolbar-left">
        <!-- Benchmark selector -->
        <div class="benchmark-selector">
          <label class="selector-label">Evaluation Benchmark</label>
          <a-select
            v-model:value="selectedBenchmarkId"
            placeholder="Select an evaluation benchmark"
            style="width: 240px"
            @change="onBenchmarkChanged"
            :loading="benchmarksLoading"
          >
            <a-select-option
              v-for="benchmark in availableBenchmarks"
              :key="benchmark.benchmark_id"
              :value="benchmark.benchmark_id"
            >
              {{ benchmark.name }} ({{ benchmark.question_count }} questions)
            </a-select-option>
          </a-select>
          <a-button
            type="text"
            size="middle"
            :loading="benchmarksLoading"
            @click="() => loadBenchmarks(true)"
            :icon="h(ReloadOutlined)"
            class="refresh-benchmarks-btn"
            title="Refresh benchmark list"
          />
        </div>
      </div>
      <div class="toolbar-right">
        <!-- Retrieval settings button -->
        <a-button size="middle" @click="openSearchConfigModal" :icon="h(SettingOutlined)" />
        <!-- Start evaluation button -->
        <a-button
          type="primary"
          :loading="startingEvaluation"
          @click="startEvaluation"
          :disabled="!selectedBenchmark"
          size="middle"
        >
          Start Evaluation
        </a-button>
      </div>
    </div>

    <!-- Evaluation result area -->
    <div class="evaluation-results">
      <!-- Model configuration (shown only when benchmark is selected and requires it) -->
      <div
        v-if="
          selectedBenchmark &&
          (selectedBenchmark.has_gold_chunks || selectedBenchmark.has_gold_answers)
        "
        class="model-config-section"
      >
        <a-row :gutter="24">
          <a-col :span="12">
            <a-form-item
              :label="
                selectedBenchmark.has_gold_answers
                  ? 'Answer Generation Model (Optional)'
                  : 'Answer Generation Model (Not required for this benchmark)'
              "
            >
              <ModelSelectorComponent
                v-model:model_spec="configForm.answer_llm"
                size="small"
                :disabled="!selectedBenchmark || !selectedBenchmark.has_gold_answers"
                @select-model="(value) => (configForm.answer_llm = value)"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item
              :label="
                selectedBenchmark.has_gold_answers
                  ? 'Answer Evaluation Model (Optional)'
                  : 'Answer Evaluation Model (Not required for this benchmark)'
              "
            >
              <ModelSelectorComponent
                v-model:model_spec="configForm.judge_llm"
                size="small"
                :disabled="!selectedBenchmark || !selectedBenchmark.has_gold_answers"
                @select-model="(value) => (configForm.judge_llm = value)"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>
      </div>

      <template v-if="!selectedBenchmark">
        <div class="empty-state">
          <a-empty description="Please select a benchmark above or go to benchmark management">
            <a-space>
              <a-button @click="$emit('switch-to-benchmarks')">
                Go to Benchmark Management
              </a-button>
            </a-space>
          </a-empty>
        </div>
      </template>
      <template v-else>
        <!-- Evaluation history -->
        <div class="history-section">
          <div class="section-header">
            <h4 class="section-title">Evaluation History</h4>
            <a-button
              type="text"
              size="small"
              :loading="refreshingHistory"
              @click="refreshHistory"
              :icon="h('ReloadOutlined')"
              class="refresh-btn"
            >
              Refresh
            </a-button>
          </div>
          <a-table
            class="history-table"
            :columns="historyColumns"
            :data-source="evaluationHistory"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-tag :color="getStatusColor(record.status)">
                  {{ getStatusText(record.status) }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'overall_score'">
                <span v-if="record.overall_score !== null">
                  <a-tag :color="getScoreTagColor(record.overall_score)">
                    {{ (record.overall_score * 100).toFixed(0) }}%
                  </a-tag>
                </span>
                <span v-else>-</span>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button
                    v-if="record.status === 'completed'"
                    type="link"
                    size="small"
                    @click="viewResults(record.task_id)"
                  >
                    View Results
                  </a-button>
                  <a-popconfirm
                    title="Are you sure you want to delete this evaluation record?"
                    description="This action cannot be undone"
                    @confirm="deleteEvaluationRecord(record.task_id)"
                    ok-text="Confirm"
                    cancel-text="Cancel"
                  >
                    <a-button type="link" size="small" danger :loading="record.deleting">
                      Delete
                    </a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </div>
      </template>
    </div>
  </div>

  <!-- Evaluation result detail modal -->
  <a-modal
    v-model:open="resultModalVisible"
    :title="`Evaluation Result - ${selectedResult?.task_id?.slice(0, 8) || ''}`"
    width="1200px"
    :footer="null"
  >
    <div v-if="resultsLoading" class="loading-container">
      <a-spin size="large" />
      <p style="margin-top: 16px; color: var(--gray-600)">Loading evaluation results...</p>
    </div>

    <div v-else-if="selectedResult && detailedResults.length > 0">
      <!-- Basic information -->
      <a-descriptions
        title="Basic Information"
        :column="3"
        size="small"
        bordered
        style="margin-bottom: 20px"
      >
        <a-descriptions-item label="Task ID">{{ selectedResult.task_id }}</a-descriptions-item>
        <a-descriptions-item label="Status">
          <a-tag :color="getStatusColor(selectedResult.status)">
            {{ getStatusText(selectedResult.status) }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="Overall Score">
          <span v-if="selectedResult.overall_score !== null">
            <a-tag :color="getScoreTagColor(selectedResult.overall_score)">
              {{ (selectedResult.overall_score * 100).toFixed(1) }}%
            </a-tag>
          </span>
          <span v-else>-</span>
        </a-descriptions-item>
        <a-descriptions-item label="Total Questions">{{
          selectedResult.total_questions
        }}</a-descriptions-item>
        <a-descriptions-item label="Completed Questions">{{
          selectedResult.completed_questions
        }}</a-descriptions-item>
        <a-descriptions-item label="Total Duration">
          <span v-if="evaluationStats.totalDuration">
            {{ formatDuration(evaluationStats.totalDuration) }}
          </span>
          <span v-else>-</span>
        </a-descriptions-item>
      </a-descriptions>

      <!-- Retrieval settings and overall evaluation report -->
      <a-row :gutter="16" style="margin-bottom: 20px">
        <!-- Retrieval settings -->
        <a-col :span="12" v-if="selectedResult.retrieval_config">
          <a-card size="small" title="Retrieval Settings">
            <div class="json-viewer-container">
              <pre class="json-viewer">{{
                JSON.stringify(selectedResult.retrieval_config, null, 2)
              }}</pre>
            </div>
          </a-card>
        </a-col>

        <!-- Overall evaluation report -->
        <a-col :span="selectedResult.retrieval_config ? 12 : 24">
          <a-card size="small" title="Overall Evaluation Report">
            <!-- Retrieval metrics -->
            <div style="margin-bottom: 20px">
              <h5 style="margin-bottom: 12px; font-size: 14px; font-weight: 500">
                Retrieval Metrics
              </h5>
              <div v-if="Object.keys(evaluationStats.retrievalMetrics || {}).length > 0">
                <div
                  v-for="(value, key) in evaluationStats.retrievalMetrics"
                  :key="key"
                  class="report-metric"
                >
                  <span class="metric-label">{{ getMetricTitle(key) }}：</span>
                  <span class="metric-value" :style="{ color: getScoreColor(value) }">
                    {{ formatMetricValue(value) }}
                  </span>
                </div>
              </div>
              <span v-else class="no-metrics">-</span>
            </div>

            <!-- Answer accuracy -->
            <div>
              <h5 style="margin-bottom: 12px; font-size: 14px; font-weight: 500">
                Answer Accuracy
              </h5>
              <div class="accuracy-stats">
                <div class="accuracy-item">
                  <span class="accuracy-label">Correct Answers:</span>
                  <span class="accuracy-value"
                    >{{ evaluationStats.correctAnswers || 0 }} /
                    {{ evaluationStats.totalQuestions || 0 }}</span
                  >
                </div>
                <div class="accuracy-item">
                  <span class="accuracy-label">Accuracy:</span>
                  <span
                    class="accuracy-value"
                    :style="{ color: getScoreColor(evaluationStats.answerAccuracy) }"
                  >
                    {{ (evaluationStats.answerAccuracy * 100).toFixed(1) }}%
                  </span>
                </div>
              </div>
            </div>
          </a-card>
        </a-col>
      </a-row>

      <!-- Detailed result table -->
      <div
        style="
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        "
      >
        <div>
          <h4 style="margin: 0">Detailed Evaluation Results</h4>
          <span style="font-size: 12px; color: var(--gray-600); margin-left: 8px">
            {{
              showErrorsOnly
                ? `Showing only failed results (${paginationTotal} total)`
                : `Showing all results (${paginationTotal} total)`
            }}
          </span>
        </div>
        <a-button
          type="default"
          size="small"
          @click="toggleErrorOnly"
          :class="{ 'error-only-active': showErrorsOnly }"
        >
          {{ showErrorsOnly ? 'Show All' : 'Errors Only' }}
        </a-button>
      </div>
      <a-table
        :columns="resultColumns"
        :data-source="detailedResults"
        :pagination="{
          current: currentPage,
          pageSize: pageSize,
          total: paginationTotal,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total, range) => `${range[0]}-${range[1]} of ${total}`,
          onChange: handlePageChange,
          onShowSizeChange: handlePageSizeChange
        }"
        :scroll="{ x: 1000 }"
        size="small"
        :loading="resultsLoading"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'query'">
            <a-tooltip :title="record.query">
              <div class="query-text">{{ record.query }}</div>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'generated_answer'">
            <a-tooltip :title="record.generated_answer">
              <div class="answer-text">{{ record.generated_answer || '-' }}</div>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'retrieval_score'">
            <div
              v-if="
                record.metrics &&
                Object.keys(record.metrics).some(
                  (k) =>
                    k.startsWith('recall') ||
                    k.startsWith('precision') ||
                    k === 'map' ||
                    k === 'ndcg'
                )
              "
              class="retrieval-metrics"
            >
              <div v-for="(val, key) in record.metrics" :key="key" class="metric-item">
                <span
                  v-if="
                    key.startsWith('recall') ||
                    key.startsWith('precision') ||
                    key === 'map' ||
                    key === 'ndcg'
                  "
                  class="metric-content"
                  :class="`metric-${getMetricType(key)}`"
                >
                  <span class="metric-name">{{ getMetricShortName(key) }}</span>
                  <span class="metric-value">{{ formatMetricValue(val) }}</span>
                </span>
              </div>
            </div>
            <span v-else class="no-metrics">-</span>
          </template>
          <template v-else-if="column.key === 'answer_score'">
            <div v-if="record.metrics && record.metrics.score !== undefined">
              <a-tag :color="record.metrics.score > 0.5 ? 'green' : 'red'">
                {{ record.metrics.score === 1.0 ? 'Correct' : 'Incorrect' }}
              </a-tag>
              <div v-if="record.metrics.reasoning" class="answer-reasoning">
                <a-tooltip :title="record.metrics.reasoning">
                  {{ record.metrics.reasoning }}
                </a-tooltip>
              </div>
            </div>
            <span v-else>-</span>
          </template>
        </template>
      </a-table>
    </div>

    <div v-else-if="selectedResult" class="empty-results">
      <a-empty description="No detailed result data available">
        <a-button @click="viewDetails(selectedResult)">View Basic Information</a-button>
      </a-empty>
    </div>
  </a-modal>

  <!-- Retrieval settings modal -->
  <SearchConfigModal
    v-model="searchConfigModalVisible"
    :database-id="databaseId"
    @save="handleSearchConfigSave"
  />
</template>

<script setup>
import { ref, reactive, onMounted, computed, h } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { evaluationApi } from '@/apis/knowledge_api'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import SearchConfigModal from './SearchConfigModal.vue'
import { SettingOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { useTaskerStore } from '@/stores/tasker'

const props = defineProps({
  databaseId: {
    type: String,
    required: true
  }
})

defineEmits(['switch-to-benchmarks'])

// Use task center store
const taskerStore = useTaskerStore()

// State
const selectedBenchmarkId = ref(null)
const selectedBenchmark = ref(null)
const benchmarksLoading = ref(false)
const availableBenchmarks = ref([])
const startingEvaluation = ref(false)
const evaluationHistory = ref([])
const resultModalVisible = ref(false)
const selectedResult = ref(null)
const detailedResults = ref([])
const evaluationStats = ref({})
const resultsLoading = ref(false)
const searchConfigModalVisible = ref(false)
const refreshingHistory = ref(false)
const showErrorsOnly = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
const paginationTotal = ref(0)
const paginationTotalPages = ref(0)

// Evaluation config form (uses knowledge base defaults)
const configForm = reactive({
  answer_llm: '', // Answer generation model
  judge_llm: '' // Judge model
})

// Table column definitions
const resultColumns = computed(() => {
  const columns = [
    {
      title: 'Question',
      dataIndex: 'query',
      key: 'query',
      width: 100
    },
    {
      title: 'Generated Answer',
      key: 'generated_answer',
      width: 180
    },
    {
      title: 'Answer Evaluation',
      key: 'answer_score',
      width: 260
    }
  ]

  // Check whether retrieval metric data exists
  const hasRetrievalMetrics = detailedResults.value.some((item) => {
    if (!item.metrics) return false
    return Object.keys(item.metrics).some(
      (key) =>
        key.startsWith('recall') || key.startsWith('precision') || key === 'map' || key === 'ndcg'
    )
  })

  // Add retrieval metrics column when data exists
  if (hasRetrievalMetrics) {
    columns.splice(2, 0, {
      title: 'Retrieval Metrics',
      key: 'retrieval_score',
      width: 100
    })
  }

  return columns
})

const historyColumns = [
  {
    title: 'Start Time',
    dataIndex: 'started_at',
    key: 'started_at',
    width: 180,
    customRender: ({ record }) => formatTime(record.started_at)
  },
  {
    title: 'Benchmark',
    key: 'benchmark_name',
    width: 200,
    customRender: ({ record }) => {
      // Find benchmark name by benchmark_id
      const benchmark = availableBenchmarks.value.find(
        (b) => b.benchmark_id === record.benchmark_id
      )
      return benchmark ? benchmark.name : record.benchmark_id?.slice(0, 8) || '-'
    }
  },
  {
    title: 'Status',
    dataIndex: 'status',
    key: 'status',
    width: 100
  },
  {
    title: 'Recall@10',
    key: 'recall_10',
    width: 100,
    customRender: ({ record }) => {
      // Use backend metrics.recall@10
      if (
        record.metrics &&
        record.metrics['recall@10'] !== undefined &&
        record.metrics['recall@10'] !== null
      ) {
        const recallValue = record.metrics['recall@10']
        const displayValue = formatMetricValue(recallValue)
        return h(
          'a-tag',
          {
            color: getScoreTagColor(recallValue)
          },
          displayValue
        )
      }

      // Show calculating status for running tasks
      if (record.status === 'running') {
        return h(
          'a-tag',
          {
            color: 'processing'
          },
          'Calculating'
        )
      }

      // Completed but no recall@10 data
      if (record.status === 'completed') {
        return h(
          'a-tag',
          {
            color: 'default'
          },
          'No Data'
        )
      }

      // Show dash in other cases
      return h('span', '-')
    }
  },
  {
    title: 'Actions',
    key: 'actions',
    width: 150
  }
]

// Toggle error-only mode
const toggleErrorOnly = async () => {
  resultsLoading.value = true
  showErrorsOnly.value = !showErrorsOnly.value
  currentPage.value = 1 // Reset to first page when mode changes

  // Load new paginated data immediately
  await loadResultsWithPagination()
}

// Handle page changes
const handlePageChange = (page, size) => {
  currentPage.value = page
  if (size !== pageSize.value) {
    pageSize.value = size
  }
  loadResultsWithPagination()
}

// Handle page size changes
const handlePageSizeChange = (current, size) => {
  currentPage.value = 1
  pageSize.value = size
  loadResultsWithPagination()
}

// Load paginated results
const loadResultsWithPagination = async () => {
  if (!selectedResult.value) return

  try {
    resultsLoading.value = true
    const response = await evaluationApi.getEvaluationResultsByDb(
      props.databaseId,
      selectedResult.value.task_id,
      {
        page: currentPage.value,
        pageSize: pageSize.value,
        errorOnly: showErrorsOnly.value
      }
    )

    if (response.message === 'success' && response.data) {
      const resultData = response.data

      // Update detailed results
      detailedResults.value = resultData.interim_results || []

      // Update pagination data
      if (resultData.pagination) {
        paginationTotal.value = resultData.pagination.total
        paginationTotalPages.value = resultData.pagination.total_pages
      } else {
        // Backward compatibility for old response format
        paginationTotal.value = detailedResults.value.length
        paginationTotalPages.value = 1
      }

      // Update statistics
      // In filter mode, calculate stats based on filtered totals
      if (showErrorsOnly.value) {
        // In filter mode, only compute current-page stats (avoid duplicate calculation)
        evaluationStats.value = {
          ...evaluationStats.value,
          totalQuestions: paginationTotal.value
          // Additional filtered statistics can be added here
        }
      } else if (currentPage.value === 1) {
        // Compute full stats only on first page in non-filter mode
        evaluationStats.value = calculateEvaluationStats(detailedResults.value)
      }

      // Update other basic fields while preserving existing values
      if (resultData.started_at && resultData.completed_at) {
        const startTime = new Date(resultData.started_at)
        const endTime = new Date(resultData.completed_at)
        evaluationStats.value.totalDuration = (endTime - startTime) / 1000
      }
    }
  } catch (error) {
    console.error('Failed to load evaluation results:', error)
    message.error('Failed to load evaluation results')
  } finally {
    resultsLoading.value = false
  }
}

// Open retrieval settings modal
const openSearchConfigModal = () => {
  searchConfigModalVisible.value = true
}

// Handle retrieval settings save
const handleSearchConfigSave = (config) => {
  console.log('Updated retrieval settings in RAG evaluation:', config)
  // Additional post-save handling can be added here
}

// Load benchmark list
const loadBenchmarks = async (showSuccessMessage = false) => {
  if (!props.databaseId) return

  benchmarksLoading.value = true
  try {
    const response = await evaluationApi.getBenchmarks(props.databaseId)

    if (response && response.message === 'success' && Array.isArray(response.data)) {
      availableBenchmarks.value = response.data

      // If no benchmark is selected, select the first available benchmark
      if (!selectedBenchmarkId.value && response.data.length > 0) {
        selectedBenchmarkId.value = response.data[0].benchmark_id
        selectedBenchmark.value = response.data[0]
      } else if (selectedBenchmarkId.value) {
        // If benchmark was selected before, verify it is still valid
        const exists = response.data.some((b) => b.benchmark_id === selectedBenchmarkId.value)
        if (!exists) {
          selectedBenchmarkId.value = null
          selectedBenchmark.value = null
        } else {
          // Update selected benchmark object
          selectedBenchmark.value = response.data.find(
            (b) => b.benchmark_id === selectedBenchmarkId.value
          )
        }
      }

      // Show success toast for manual refresh
      if (showSuccessMessage) {
        message.success(`Refreshed: found ${response.data.length} benchmarks`)
      }
    } else {
      console.error('Unexpected response format:', response)
      message.error('Invalid benchmark data format')
    }
  } catch (error) {
    console.error('Failed to load evaluation benchmarks:', error)
    message.error('Failed to load evaluation benchmarks')
  } finally {
    benchmarksLoading.value = false
  }
}

// Handle selector change
const onBenchmarkChanged = (benchmarkId) => {
  const benchmark = availableBenchmarks.value.find((b) => b.benchmark_id === benchmarkId)
  selectedBenchmark.value = benchmark || null
}

// Refresh evaluation history
const refreshHistory = async () => {
  refreshingHistory.value = true
  try {
    await loadEvaluationHistory()
    message.success('History refreshed')
  } catch (error) {
    console.error('Failed to refresh history:', error)
    message.error('Failed to refresh history')
  } finally {
    refreshingHistory.value = false
  }
}

// Start evaluation
const startEvaluation = async () => {
  if (!selectedBenchmark.value) {
    message.error('Please select an evaluation benchmark first')
    return
  }

  // Validate model selection: both models must be selected together or both left empty
  const hasAnswerModel = !!configForm.answer_llm
  const hasJudgeModel = !!configForm.judge_llm

  if (hasAnswerModel !== hasJudgeModel) {
    message.warning(
      'Generation model and evaluation model must both be selected or both left empty'
    )
    return
  }

  const runEvaluation = async () => {
    startingEvaluation.value = true

    // Only send model config; retrieval config is read by server from the knowledge base
    const params = {
      benchmark_id: selectedBenchmark.value.benchmark_id,
      model_config: {
        answer_llm: configForm.answer_llm, // answer generation model
        judge_llm: configForm.judge_llm // judge model
      }
    }

    try {
      const response = await evaluationApi.runEvaluation(props.databaseId, params)

      if (response.message === 'success') {
        message.success('Evaluation task started')
        loadEvaluationHistory()
        // Refresh task center list
        taskerStore.loadTasks()
      } else {
        message.error(response.message || 'Failed to start evaluation')
      }
    } catch (error) {
      console.error('Failed to start evaluation:', error)
      message.error('Failed to start evaluation')
    } finally {
      startingEvaluation.value = false
    }
  }

  if (!hasAnswerModel) {
    Modal.confirm({
      title: 'Confirm Evaluation Mode',
      content:
        'No answer generation model is selected. Only retrieval evaluation will run, without QA evaluation. Continue?',
      okText: 'Continue',
      cancelText: 'Cancel',
      onOk: runEvaluation
    })
  } else {
    runEvaluation()
  }
}

// Load evaluation history
const loadEvaluationHistory = async () => {
  try {
    const response = await evaluationApi.getEvaluationHistory(props.databaseId)
    if (response.message === 'success') {
      evaluationHistory.value = response.data || []
    }
  } catch (error) {
    console.error('Failed to load evaluation history:', error)
    message.error('Failed to load evaluation history')
  }
}

// Calculate evaluation statistics
const calculateEvaluationStats = (results) => {
  if (!results || results.length === 0) {
    return {}
  }

  const stats = {
    totalQuestions: results.length,
    retrievalMetrics: {},
    answerAccuracy: 0,
    correctAnswers: 0,
    averageResponseTime: 0,
    totalResponseTime: 0
  }

  const metricSums = {}
  const metricCounts = {}

  results.forEach((item) => {
    // Answer accuracy
    if (item.metrics && item.metrics.score !== undefined) {
      if (item.metrics.score > 0.5) {
        stats.correctAnswers++
      }
    }

    // Retrieval metric aggregation
    if (item.metrics) {
      Object.keys(item.metrics).forEach((key) => {
        if (
          key.startsWith('recall') ||
          key.startsWith('precision') ||
          key === 'map' ||
          key === 'ndcg'
        ) {
          if (!metricSums[key]) {
            metricSums[key] = 0
            metricCounts[key] = 0
          }
          metricSums[key] += item.metrics[key]
          metricCounts[key]++
        }
      })
    }
  })

  // Compute averages
  Object.keys(metricSums).forEach((key) => {
    stats.retrievalMetrics[key] = metricSums[key] / metricCounts[key]
  })

  // Compute answer accuracy
  stats.answerAccuracy = stats.totalQuestions > 0 ? stats.correctAnswers / stats.totalQuestions : 0

  return stats
}

// View results
const viewResults = async (taskId) => {
  try {
    resultsLoading.value = true

    // Reset pagination state
    currentPage.value = 1
    showErrorsOnly.value = false

    // Fetch basic information first (without pagination)
    const response = await evaluationApi.getEvaluationResultsByDb(props.databaseId, taskId)

    if (response.message === 'success' && response.data) {
      const resultData = response.data

      // Use history task info when available, otherwise fallback to API response
      selectedResult.value = evaluationHistory.value.find((r) => r.task_id === taskId) || {
        task_id: resultData.task_id,
        status: resultData.status,
        started_at: resultData.started_at,
        completed_at: resultData.completed_at,
        total_questions: resultData.total_questions || 0,
        completed_questions: resultData.completed_questions || 0,
        overall_score: resultData.overall_score,
        retrieval_config: resultData.retrieval_config
      }

      // If sourced from history, ensure retrieval_config is set
      if (selectedResult.value && !selectedResult.value.retrieval_config) {
        selectedResult.value.retrieval_config = resultData.retrieval_config
      }

      // Open modal
      resultModalVisible.value = true

      // Load paginated data
      await loadResultsWithPagination()
    } else {
      message.error('Failed to fetch evaluation results: invalid data format')
    }
  } catch (error) {
    console.error('Failed to fetch evaluation results:', error)
    message.error('Failed to fetch evaluation results')
  } finally {
    resultsLoading.value = false
  }
}

// Delete evaluation record
const deleteEvaluationRecord = async (taskId) => {
  try {
    // Find record and set loading state
    const record = evaluationHistory.value.find((r) => r.task_id === taskId)
    if (record) {
      record.deleting = true
    }

    const response = await evaluationApi.deleteEvaluationResultByDb(props.databaseId, taskId)
    if (response.message === 'success') {
      message.success('Deleted successfully')
      // Reload evaluation history
      await loadEvaluationHistory()
    }
  } catch (error) {
    console.error('Failed to delete evaluation record:', error)
    message.error('Failed to delete evaluation record')
  } finally {
    // Clear loading state
    const record = evaluationHistory.value.find((r) => r.task_id === taskId)
    if (record) {
      record.deleting = false
    }
  }
}

const formatTime = (timeStr) => {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  return date.toLocaleString('en-US')
}

const getScoreColor = (score) => {
  if (score >= 0.8) return 'var(--color-success-500)'
  if (score >= 0.6) return 'var(--color-warning-500)'
  return 'var(--color-error-500)'
}

const getScoreTagColor = (score) => {
  if (score >= 0.8) return 'success'
  if (score >= 0.6) return 'warning'
  return 'error'
}

const getStatusColor = (status) => {
  const colors = {
    running: 'blue',
    completed: 'green',
    failed: 'red',
    paused: 'orange'
  }
  return colors[status] || 'default'
}

const getStatusText = (status) => {
  const texts = {
    running: 'Running',
    completed: 'Completed',
    failed: 'Failed',
    paused: 'Paused'
  }
  return texts[status] || status
}

const getMetricTitle = (key) => {
  const titles = {
    precision: 'Precision',
    recall: 'Recall',
    map: 'Mean Average Precision',
    ndcg: 'NDCG',
    bleu: 'BLEU Score',
    rouge: 'ROUGE Score',
    answer_correctness: 'Answer Correctness',
    score: 'Score',
    reasoning: 'Reasoning',
    overall_score: 'Overall Score'
  }
  // Handle recall@k and precision@k
  if (key.startsWith('recall@')) return `Recall (${key.split('@')[1]})`
  if (key.startsWith('precision@')) return `Precision (${key.split('@')[1]})`

  return titles[key] || key
}

// Get metric type
const getMetricType = (key) => {
  if (key.startsWith('recall')) return 'recall'
  if (key.startsWith('precision')) return 'precision'
  if (key === 'map') return 'map'
  if (key === 'ndcg') return 'ndcg'
  return 'default'
}

// Get short metric name
const getMetricShortName = (key) => {
  if (key.startsWith('recall@')) return `R@${key.split('@')[1]}`
  if (key.startsWith('precision@')) return `P@${key.split('@')[1]}`
  if (key === 'precision') return 'Precision'
  if (key === 'recall') return 'Recall'
  if (key === 'map') return 'MAP'
  if (key === 'ndcg') return 'NDCG'
  return key
}

// Format metric value
const formatMetricValue = (val) => {
  if (typeof val !== 'number') return '-'
  // Retrieval metrics (recall, precision, f1, etc.) are usually 0.0-1.0; convert to percentage
  if (val <= 1) return (val * 100).toFixed(1) + '%'
  return val.toFixed(3)
}

// Format duration
const formatDuration = (seconds) => {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = Math.round(seconds % 60)
    return `${minutes}m ${remainingSeconds}s`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}h ${minutes}m`
  }
}

// Load data on component mount
onMounted(() => {
  loadBenchmarks()
  loadEvaluationHistory()
})
</script>

<style lang="less" scoped>
.rag-evaluation-container {
  height: 100%;
  background: var(--gray-0);
  display: flex;
  flex-direction: column;
}

// Top toolbar
.toolbar {
  padding: 12px 16px;
  background: var(--gray-0);
  border-bottom: 1px solid var(--gray-200);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;

  .toolbar-left {
    display: flex;
    align-items: center;
  }

  .benchmark-selector {
    display: flex;
    align-items: center;
    gap: 12px;

    .selector-label {
      font-size: 14px;
      font-weight: 500;
      color: var(--gray-700);
      margin: 0;
      white-space: nowrap;
    }

    .refresh-benchmarks-btn {
      color: var(--gray-600);
    }
  }

  .toolbar-right {
    display: flex;
    align-items: center;
    gap: 6px;
  }
}

// Evaluation content area
.evaluation-content {
  flex: 1;
  overflow: hidden;
  min-height: 0;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

// Evaluation results area
.evaluation-results {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
  padding: 16px;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    background-color: rgba(0, 0, 0, 0.2);
    border-radius: 3px;

    &:hover {
      background-color: rgba(0, 0, 0, 0.3);
    }
  }
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-0);
  border-radius: 8px;
  border: 1px solid var(--gray-200);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;

  .progress-stats {
    flex: 1;
    margin-right: 24px;
    min-width: 300px;

    .ant-statistic {
      margin-bottom: 12px;

      .ant-statistic-title {
        font-size: 13px;
        color: var(--gray-600);
      }

      .ant-statistic-content {
        font-size: 18px;
        font-weight: 500;
      }
    }
  }

  .progress-actions {
    flex-shrink: 0;
    padding-top: 24px;
  }
}

.query-text {
  font-size: 12px;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  line-height: 1.5;
  word-wrap: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
}

.answer-text {
  font-size: 12px;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  line-height: 1.5;
  word-wrap: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--gray-700);
}

.log-time {
  color: var(--gray-500);
  margin-left: 8px;
  font-size: 12px;
}

// Table style improvements
:deep(.ant-table) {
  .ant-table-tbody > tr > td {
    padding: 12px 12px;
    vertical-align: top;
  }

  .ant-table-thead > tr > th {
    padding: 8px 12px;
    font-weight: 500;
    background-color: var(--gray-50);
  }
}

// Card spacing adjustments
:deep(.ant-card) {
  .ant-card-head {
    padding: 8px 16px;
    min-height: 40px;

    .ant-card-head-title {
      font-size: 14px;
      font-weight: 500;
      padding: 4px 0;
    }
  }
}

// Timeline style adjustments
:deep(.ant-timeline) {
  .ant-timeline-item-content {
    margin-left: 20px;
    padding-bottom: 12px;
  }
}

// Description list style adjustments
:deep(.ant-descriptions) {
  .ant-descriptions-item-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--gray-600);
  }

  .ant-descriptions-item-content {
    font-size: 13px;
  }
}

// Form item spacing adjustments
:deep(.ant-form) {
  .ant-form-item {
    margin-bottom: 16px;
  }
}

:deep(.ant-form-inline) {
  .ant-form-item {
    margin-right: 24px;
    margin-bottom: 16px;

    &:last-child {
      margin-right: 0;
    }
  }
}

// Model config form style adjustments
.model-config-section {
  padding: 6px 8px;
  background: var(--gray-10);
  border-radius: 8px;
  border: 1px solid var(--gray-150);

  .ant-form-item {
    margin-bottom: 0;

    .ant-form-item-label {
      font-weight: 500;
    }

    .ant-form-item-extra {
      font-size: 12px;
      color: var(--gray-500);
      margin-top: 4px;
    }
  }

  // Add specific styling for columns inside model config section
  .ant-col {
    &:not(:last-child) .ant-form-item {
      padding-right: 12px;
    }
  }
}

// Statistic number style adjustments
:deep(.ant-row) {
  .ant-col {
    .ant-statistic {
      padding: 12px;
      border: 1px solid var(--gray-200);
      border-radius: 6px;
      text-align: center;
      transition: all 0.3s;

      &:hover {
        border-color: var(--gray-300);
        box-shadow: 0 2px 4px var(--shadow-1);
      }
    }
  }
}

// Retrieval metric styles
.retrieval-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 20px;
  align-items: center;
}

.metric-item {
  display: flex;
  align-items: center;
}

.metric-content {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.4;
  font-weight: 500;
  white-space: nowrap;

  &.metric-recall {
    background-color: var(--color-info-50);
    color: var(--color-info-900);
  }

  &.metric-precision {
    background-color: var(--color-success-50);
    color: var(--color-success-900);
  }

  &.metric-map,
  &.metric-ndcg {
    background-color: var(--color-accent-50);
    color: var(--color-accent-900);
  }
}

.metric-name {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.metric-value {
  font-weight: 700;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
}

.no-metrics {
  color: var(--gray-400);
  font-style: italic;
}

// Answer reasoning styles
.answer-reasoning {
  font-size: 12px;
  color: var(--gray-600);
  margin-top: 8px;
  line-height: 1.4;
  cursor: pointer;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  word-wrap: break-word;
  overflow: hidden;
  text-overflow: ellipsis;

  &:hover {
    color: var(--gray-800);
  }
}

// Loading and empty state styles
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
}

.empty-results {
  padding: 40px 0;
  text-align: center;
}

// Evaluation report styles
.evaluation-report {
  margin-bottom: 20px;

  .report-metric {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--gray-100);

    &:last-child {
      border-bottom: none;
    }

    .metric-label {
      font-size: 14px;
      padding-right: 18px;
      color: var(--gray-700);
    }

    .metric-value {
      font-size: 14px;
      font-weight: 600;
      font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
    }
  }

  .accuracy-stats {
    .accuracy-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px solid var(--gray-100);

      &:last-child {
        border-bottom: none;
      }

      .accuracy-label {
        font-size: 14px;
        color: var(--gray-700);
      }

      .accuracy-value {
        font-size: 16px;
        font-weight: 600;
        font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
      }
    }
  }

  :deep(.ant-card) {
    .ant-card-head {
      border-bottom: 1px solid var(--gray-200);

      .ant-card-head-title {
        font-size: 14px;
        font-weight: 500;
      }
    }
  }
}

// Evaluation history section
.history-section {
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;

    .section-title {
      margin: 0;
      font-size: 14px;
      font-weight: 500;
      color: var(--gray-700);
    }

    .refresh-btn {
      color: var(--gray-600);
      border: none;
      box-shadow: none;
      padding: 4px 8px;
      height: auto;
      font-size: 13px;

      &:hover {
        color: var(--color-primary-600);
        background-color: var(--color-primary-50);
      }

      &:active {
        color: var(--color-primary-700);
        background-color: var(--color-primary-100);
      }

      .anticon {
        font-size: 14px;
      }
    }
  }

  :deep(.ant-table) {
    border: 1px solid var(--gray-100);
  }
}

// JSON viewer styles
.json-viewer-container {
  max-height: 400px;
  overflow: auto;

  .json-viewer {
    margin: 0;
    padding: 0;
    font-family: 'SF Mono', 'Monaco', 'Consolas', 'Menlo', monospace;
    font-size: 13px;
    line-height: 1.5;
    color: var(--gray-800);
    white-space: pre-wrap;
    word-wrap: break-word;
    background: var(--gray-50);
    border: 1px solid var(--gray-200);
    border-radius: 6px;
    padding: 12px;
  }
}

// Error-only toggle button styles
.error-only-active {
  background-color: var(--color-error-500) !important;
  border-color: var(--color-error-500) !important;
  color: white !important;

  &:hover {
    background-color: var(--color-error-600) !important;
    border-color: var(--color-error-600) !important;
  }

  &:focus {
    background-color: var(--color-error-500) !important;
    border-color: var(--color-error-500) !important;
  }
}
</style>
