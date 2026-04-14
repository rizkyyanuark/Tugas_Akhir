<template>
  <div class="evaluation-benchmarks-container">
    <!-- Action bar -->
    <div class="benchmarks-header">
      <div class="header-left">
        <span class="total-count">{{ benchmarks.length }} benchmarks</span>
      </div>
      <div class="header-right">
        <a-button @click="loadBenchmarks">
          <template #icon><ReloadOutlined /></template>
          Refresh
        </a-button>
        <a-button type="primary" @click="showUploadModal">
          <template #icon><UploadOutlined /></template>
          Upload Benchmark
        </a-button>
        <a-button @click="showGenerateModal">
          <template #icon><RobotOutlined /></template>
          Auto Generate
        </a-button>
      </div>
    </div>

    <!-- Benchmark list -->
    <div class="benchmarks-list">
      <div v-if="!loading && benchmarks.length === 0" class="empty-state">
        <div class="empty-icon">📋</div>
        <div class="empty-title">No evaluation benchmarks yet</div>
        <div class="empty-description">Upload or generate benchmarks to get started</div>
      </div>

      <div v-else-if="loading" class="loading-state">
        <a-spin size="large" />
      </div>

      <div v-else class="benchmark-list-content">
        <div
          v-for="benchmark in benchmarks"
          :key="benchmark.benchmark_id"
          class="benchmark-item"
          @click="previewBenchmark(benchmark)"
        >
          <!-- Main content -->
          <div class="benchmark-main">
            <div class="benchmark-header">
              <h4 class="benchmark-name">{{ benchmark.name }}</h4>
              <div class="benchmark-actions">
                <a-button type="text" size="small" @click.stop="previewBenchmark(benchmark)">
                  <EyeOutlined />
                </a-button>
                <a-button
                  type="text"
                  size="small"
                  :loading="!!downloadingBenchmarkMap[benchmark.benchmark_id]"
                  @click.stop="downloadBenchmark(benchmark)"
                >
                  <DownloadOutlined />
                </a-button>
                <a-button type="text" size="small" danger @click.stop="deleteBenchmark(benchmark)">
                  <DeleteOutlined />
                </a-button>
              </div>
            </div>

            <p class="benchmark-desc">{{ benchmark.description || 'No description' }}</p>

            <!-- Tag section -->
            <div class="benchmark-meta">
              <div class="meta-row">
                <span
                  v-if="benchmark.has_gold_chunks && benchmark.has_gold_answers"
                  class="type-badge type-both"
                >
                  Retrieval + QA
                </span>
                <span v-else-if="benchmark.has_gold_chunks" class="type-badge type-retrieval">
                  Retrieval Eval
                </span>
                <span v-else-if="benchmark.has_gold_answers" class="type-badge type-answer">
                  QA Eval
                </span>
                <span v-else class="type-badge type-query">Query Only</span>

                <span :class="['tag', benchmark.has_gold_chunks ? 'tag-yes' : 'tag-no']">
                  {{ benchmark.has_gold_chunks ? '✓' : '✗' }} Gold Chunk
                </span>
                <span :class="['tag', benchmark.has_gold_answers ? 'tag-yes' : 'tag-no']">
                  {{ benchmark.has_gold_answers ? '✓' : '✗' }} Gold Answer
                </span>
              </div>
            </div>
          </div>

          <!-- Footer info -->
          <div class="benchmark-footer">
            <span class="benchmark-time">{{ formatDate(benchmark.created_at) }}</span>
            <span class="benchmark-count">{{ benchmark.question_count }} questions</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Upload modal -->
    <BenchmarkUploadModal
      v-model:visible="uploadModalVisible"
      :database-id="databaseId"
      @success="onUploadSuccess"
    />

    <!-- Generate modal -->
    <BenchmarkGenerateModal
      v-model:visible="generateModalVisible"
      :database-id="databaseId"
      @success="onGenerateSuccess"
    />

    <!-- Preview modal -->
    <a-modal
      v-model:open="previewModalVisible"
      title="Evaluation Benchmark Details"
      width="1200px"
      :footer="null"
    >
      <div v-if="previewData" class="preview-content">
        <div class="preview-header">
          <h3>{{ previewData.name }}</h3>
          <div class="preview-meta">
            <span class="meta-item">
              <span class="meta-label">Question Count:</span>
              {{ previewData.question_count }}
            </span>
            <span class="meta-item">
              <span class="meta-label">Gold Chunk:</span>
              <span :class="previewData.has_gold_chunks ? 'status-yes' : 'status-no'">
                {{ previewData.has_gold_chunks ? 'Yes' : 'No' }}
              </span>
            </span>
            <span class="meta-item">
              <span class="meta-label">Gold Answer:</span>
              <span :class="previewData.has_gold_answers ? 'status-yes' : 'status-no'">
                {{ previewData.has_gold_answers ? 'Yes' : 'No' }}
              </span>
            </span>
          </div>
        </div>

        <div class="preview-questions" v-if="previewQuestions && previewQuestions.length > 0">
          <h4>Question List ({{ previewPagination.total }} total)</h4>
          <a-table
            :dataSource="previewQuestions"
            :columns="displayedQuestionColumns"
            :pagination="paginationConfig"
            size="small"
            :rowKey="(_, index) => index"
            :loading="previewPagination.loading"
          >
            <template #bodyCell="{ column, record, index }">
              <template v-if="column.key === 'index'">
                <span class="question-num"
                  >Q{{
                    (previewPagination.current - 1) * previewPagination.pageSize + index + 1
                  }}</span
                >
              </template>
              <template v-if="column.key === 'query'">
                <a-tooltip :title="record?.query || ''" placement="topLeft">
                  <div class="question-text">{{ record?.query || '' }}</div>
                </a-tooltip>
              </template>
              <template v-if="column.key === 'gold_chunk_ids'">
                <a-tooltip
                  v-if="record?.gold_chunk_ids && record.gold_chunk_ids.length > 0"
                  :title="record.gold_chunk_ids.join(', ')"
                  placement="topLeft"
                >
                  <div class="question-chunk">
                    {{ record.gold_chunk_ids.slice(0, 3).join(', ') }}
                    <span v-if="record.gold_chunk_ids.length > 3"
                      >...and {{ record.gold_chunk_ids.length }} more</span
                    >
                  </div>
                </a-tooltip>
                <span v-else class="no-data">-</span>
              </template>
              <template v-if="column.key === 'gold_answer'">
                <a-tooltip
                  v-if="record?.gold_answer"
                  :title="record.gold_answer"
                  placement="topLeft"
                >
                  <div class="question-answer">
                    {{ record.gold_answer }}
                  </div>
                </a-tooltip>
                <span v-else class="no-data">-</span>
              </template>
            </template>
          </a-table>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  UploadOutlined,
  RobotOutlined,
  EyeOutlined,
  DownloadOutlined,
  DeleteOutlined,
  ReloadOutlined
} from '@ant-design/icons-vue'
import { evaluationApi } from '@/apis/knowledge_api'
import { useTaskerStore } from '@/stores/tasker'
import BenchmarkUploadModal from './modals/BenchmarkUploadModal.vue'
import BenchmarkGenerateModal from './modals/BenchmarkGenerateModal.vue'

const props = defineProps({
  databaseId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['refresh'])

const taskerStore = useTaskerStore()

// State
const loading = ref(false)
const benchmarks = ref([])
const uploadModalVisible = ref(false)
const generateModalVisible = ref(false)
const previewModalVisible = ref(false)
const previewData = ref(null)
const previewQuestions = ref([])
const downloadingBenchmarkMap = reactive({})
const previewPagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  loading: false
})

// Table column definitions
const questionColumns = [
  {
    title: '#',
    key: 'index',
    width: 60,
    align: 'center'
  },
  {
    title: 'Question',
    dataIndex: 'query',
    key: 'query',
    width: 280,
    ellipsis: false
  },
  {
    title: 'Gold Chunk',
    dataIndex: 'gold_chunk_ids',
    key: 'gold_chunk_ids',
    width: 200,
    ellipsis: false
  },
  {
    title: 'Gold Answer',
    dataIndex: 'gold_answer',
    key: 'gold_answer',
    width: 420,
    ellipsis: false
  }
]

const displayedQuestionColumns = computed(() => {
  if (previewData.value && previewData.value.has_gold_chunks === false) {
    return questionColumns.filter((c) => c.key !== 'gold_chunk_ids')
  }
  return questionColumns
})

// Pagination config
const paginationConfig = computed(() => ({
  current: previewPagination.value.current,
  pageSize: previewPagination.value.pageSize,
  total: previewPagination.value.total,
  showTotal: (total, range) => `${range[0]}-${range[1]} of ${total}`,
  showSizeChanger: true,
  pageSizeOptions: ['5', '10', '20', '50'],
  showQuickJumper: true,
  size: 'small',
  onChange: handlePageChange,
  onShowSizeChange: handlePageSizeChange
}))

// Load benchmark list
const loadBenchmarks = async () => {
  if (!props.databaseId) return

  loading.value = true
  try {
    const response = await evaluationApi.getBenchmarks(props.databaseId)

    if (response && response.message === 'success' && Array.isArray(response.data)) {
      benchmarks.value = response.data
    } else {
      console.error('Unexpected response format:', response)
      message.error('Invalid benchmark data format')
    }
  } catch (error) {
    console.error('Failed to load evaluation benchmarks:', error)
    message.error('Failed to load evaluation benchmarks')
  } finally {
    loading.value = false
  }
}

// Show upload modal
const showUploadModal = () => {
  uploadModalVisible.value = true
}

// Show generate modal
const showGenerateModal = () => {
  generateModalVisible.value = true
}

// Upload success callback
const onUploadSuccess = () => {
  loadBenchmarks()
  message.success('Benchmark uploaded successfully')
  taskerStore.loadTasks() // Refresh task list
  // Notify parent component to refresh benchmark list
  emit('refresh')
}

// Generation success callback
const onGenerateSuccess = () => {
  loadBenchmarks()
  // message.success('Benchmark generated successfully'); // Removed, modal handles submission notice
  taskerStore.loadTasks() // Refresh task list
  // Notify parent component to refresh benchmark list
  emit('refresh')
}

// Pagination handlers
const handlePageChange = (page, pageSize) => {
  previewPagination.value.current = page
  previewPagination.value.pageSize = pageSize
  loadPreviewQuestions()
}

const handlePageSizeChange = (current, size) => {
  previewPagination.value.current = 1
  previewPagination.value.pageSize = size
  loadPreviewQuestions()
}

// Load preview questions (paginated)
const loadPreviewQuestions = async () => {
  if (!previewData.value?.benchmark_id) return

  try {
    previewPagination.value.loading = true
    const response = await evaluationApi.getBenchmarkByDb(
      props.databaseId,
      previewData.value.benchmark_id,
      previewPagination.value.current,
      previewPagination.value.pageSize
    )

    if (response.message === 'success') {
      previewQuestions.value = response.data.questions || []
      previewPagination.value.total = response.data.pagination?.total_questions || 0
    }
  } catch (error) {
    console.error('Failed to load preview questions:', error)
    message.error('Failed to load preview questions')
  } finally {
    previewPagination.value.loading = false
  }
}

// Preview benchmark
const previewBenchmark = async (benchmark) => {
  try {
    // Reset pagination state
    previewPagination.value = {
      current: 1,
      pageSize: 10,
      total: 0,
      loading: false
    }

    const response = await evaluationApi.getBenchmarkByDb(
      props.databaseId,
      benchmark.benchmark_id,
      previewPagination.value.current,
      previewPagination.value.pageSize
    )

    if (response.message === 'success') {
      // Save benchmark ID for subsequent pagination requests
      previewData.value = {
        ...response.data,
        benchmark_id: benchmark.benchmark_id // Manually include benchmark_id
      }
      previewQuestions.value = response.data.questions || []
      previewPagination.value.total = response.data.pagination?.total_questions || 0
      console.log('Preview question data:', response.data.questions) // Debug info
      previewModalVisible.value = true
    }
  } catch (error) {
    console.error('Failed to get benchmark details:', error)
    message.error('Failed to get benchmark details')
  }
}

const parseDownloadFilename = (contentDisposition) => {
  if (!contentDisposition) return ''

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch (error) {
      console.warn('Failed to parse UTF-8 filename:', error)
    }
  }

  const asciiMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  if (asciiMatch && asciiMatch[1]) {
    return asciiMatch[1]
  }

  return ''
}

// Download benchmark
const downloadBenchmark = async (benchmark) => {
  const benchmarkId = benchmark?.benchmark_id
  if (!benchmarkId) return
  if (downloadingBenchmarkMap[benchmarkId]) return

  downloadingBenchmarkMap[benchmarkId] = true
  try {
    const response = await evaluationApi.downloadBenchmark(benchmarkId)
    const blob = await response.blob()
    const contentDisposition =
      response.headers.get('Content-Disposition') || response.headers.get('content-disposition')
    const headerFilename = parseDownloadFilename(contentDisposition)
    const fallbackFilename = `${benchmark.name || benchmarkId}.jsonl`
    const filename = headerFilename || fallbackFilename

    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    message.success('Download successful')
  } catch (error) {
    console.error('Failed to download benchmark:', error)
    message.error(`Download failed: ${error.message || 'Unknown error'}`)
  } finally {
    delete downloadingBenchmarkMap[benchmarkId]
  }
}

// Delete benchmark
const deleteBenchmark = (benchmark) => {
  Modal.confirm({
    title: 'Confirm Deletion',
    content: `Are you sure you want to delete evaluation benchmark "${benchmark.name}"? This action cannot be undone.`,
    okText: 'Confirm',
    cancelText: 'Cancel',
    onOk: async () => {
      try {
        const response = await evaluationApi.deleteBenchmark(benchmark.benchmark_id)
        if (response.message === 'success') {
          message.success('Deleted successfully')
          loadBenchmarks()
        }
      } catch (error) {
        console.error('Failed to delete benchmark:', error)
        message.error('Failed to delete benchmark')
      }
    }
  })
}

// Format date
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// Load data when component mounts
onMounted(() => {
  loadBenchmarks()
})
</script>

<style lang="less" scoped>
.evaluation-benchmarks-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.benchmarks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  margin-bottom: 12px;

  .total-count {
    font-size: 13px;
    color: var(--color-text-secondary);
  }

  .header-right {
    display: flex;
    gap: 8px;
  }
}

.benchmarks-list {
  flex: 1;
  overflow-y: auto;
}

.benchmark-list-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.benchmark-item {
  padding: 12px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--color-bg-container);
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: var(--color-primary-100);
    box-shadow: 0 1px 2px var(--shadow-2);
    background: var(--gray-10);
  }

  &:active {
    transform: scale(0.998);
  }
}

.benchmark-main {
  margin-bottom: 8px;
}

.benchmark-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 6px;

  .benchmark-name {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--gray-1000);
    flex: 1;
  }

  .benchmark-actions {
    display: flex;
    gap: 4px;
  }
}

.benchmark-desc {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.benchmark-meta {
  margin-bottom: 8px;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  background: var(--main-50);
  color: var(--color-text-tertiary);

  &.tag-yes {
    // background: var(--color-success-50);
    color: var(--main-500);
  }
}

.type-badge {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;

  &.type-both {
    background: var(--color-accent-50);
    color: var(--color-accent-700);
  }

  &.type-retrieval {
    background: var(--color-info-50);
    color: var(--color-info-700);
  }

  &.type-answer {
    background: var(--color-warning-50);
    color: var(--color-warning-700);
  }

  &.type-query {
    background: var(--gray-100);
    color: var(--gray-700);
  }
}

.benchmark-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid var(--gray-150);
  font-size: 11px;
  color: var(--color-text-tertiary);

  .benchmark-id {
    font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  }

  .benchmark-count {
    color: var(--color-primary-700);
    font-weight: 500;
  }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 300px;
  text-align: center;

  .empty-icon {
    font-size: 48px;
    margin-bottom: 16px;
    opacity: 0.5;
  }

  .empty-title {
    font-size: 18px;
    font-weight: 500;
    color: var(--gray-900);
    margin-bottom: 8px;
  }

  .empty-description {
    font-size: 14px;
    color: var(--gray-600);
  }
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
}

// Preview modal styles
.preview-content {
  .preview-header {
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--gray-200);

    h3 {
      margin: 0 0 12px;
      font-size: 20px;
      font-weight: 600;
      color: var(--gray-1000);
    }

    .preview-meta {
      display: flex;
      gap: 24px;

      .meta-item {
        font-size: 14px;

        .meta-label {
          color: var(--color-text-tertiary);
          margin-right: 4px;
        }

        .status-yes {
          color: var(--color-success-700);
          font-weight: 500;
        }

        .status-no {
          color: var(--color-text-tertiary);
        }
      }
    }
  }

  .preview-questions {
    h4 {
      margin: 0 0 16px;
      font-size: 16px;
      font-weight: 600;
      color: var(--gray-900);
    }

    .question-num {
      font-size: 14px;
      font-weight: 600;
      color: var(--gray-700);
    }

    .question-text {
      font-size: 14px;
      line-height: 1.5;
      color: var(--gray-800);
      word-break: break-all;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
      max-height: 6em; // 4 lines * 1.5em line-height
      cursor: pointer;
    }

    .question-chunk,
    .question-answer {
      font-size: 13px;
      color: var(--gray-600);
      word-break: break-all;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
      max-height: 6em; // 4 lines * 1.5em line-height for 13px font
      cursor: pointer;
    }

    .no-data {
      color: var(--gray-400);
      font-style: italic;
    }

    :deep(.ant-table) {
      .ant-table-thead > tr > th {
        background-color: var(--gray-50);
        border-bottom: 1px solid var(--gray-200);
        font-weight: 600;
        font-size: 13px;
        padding: 8px 12px;
        white-space: nowrap;
      }

      .ant-table-tbody > tr > td {
        padding: 8px 12px;
        border-bottom: 1px solid var(--gray-150);
        font-size: 13px;
        vertical-align: top;
        line-height: 1.4;
      }

      .ant-table-tbody > tr:hover > td {
        background-color: var(--gray-50);
      }

      // Ensure table cell content can wrap
      .ant-table-cell {
        white-space: normal !important;
        word-wrap: break-word !important;
        word-break: break-all !important;
      }
    }
  }
}
</style>
