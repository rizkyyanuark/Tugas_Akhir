<template>
  <section class="alias-curation">
    <div class="toolbar">
      <div class="summary">
        <div class="summary-item">
          <span class="summary-label">Pending</span>
          <strong>{{ counts.pending || 0 }}</strong>
        </div>
        <div class="summary-item">
          <span class="summary-label">Approved</span>
          <strong>{{ counts.approved || 0 }}</strong>
        </div>
        <div class="summary-item">
          <span class="summary-label">Rejected</span>
          <strong>{{ counts.rejected || 0 }}</strong>
        </div>
      </div>
      <div class="actions">
        <a-select v-model:value="statusFilter" style="width: 150px" @change="loadSuggestions">
          <a-select-option value="all">All</a-select-option>
          <a-select-option value="pending">Pending</a-select-option>
          <a-select-option value="approved">Approved</a-select-option>
          <a-select-option value="rejected">Rejected</a-select-option>
        </a-select>
        <a-button @click="syncSuggestions" :loading="state.syncing">Sync Suggestions</a-button>
        <a-button type="primary" @click="exportAliases" :loading="state.exporting">
          Export Approved YAML
        </a-button>
      </div>
    </div>

    <a-alert
      class="path-note"
      type="info"
      show-icon
      :message="pathMessage"
    />

    <a-table
      :columns="columns"
      :data-source="suggestions"
      :loading="state.loading"
      :pagination="{ pageSize: 10, showSizeChanger: true }"
      row-key="id"
      size="middle"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'raw'">
          <div class="raw-cell">
            <strong>{{ record.raw_label || '-' }}</strong>
            <span>{{ record.concept_type || 'ResearchTopic' }}</span>
          </div>
        </template>
        <template v-else-if="column.key === 'canonical'">
          <div class="canonical-cell">
            <strong>{{ displayCanonical(record) }}</strong>
            <code>{{ displayCanonicalKey(record) }}</code>
          </div>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="statusColor(record)">
            {{ decisionStatus(record) }}
          </a-tag>
          <a-tag v-if="record.review_status" color="blue">
            {{ record.review_status }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'confidence'">
          <span>{{ formatConfidence(record.confidence) }}</span>
        </template>
        <template v-else-if="column.key === 'aliases'">
          <div class="alias-list">
            <a-tag v-for="alias in previewAliases(record)" :key="alias">
              {{ alias }}
            </a-tag>
          </div>
        </template>
        <template v-else-if="column.key === 'actions'">
          <div class="row-actions">
            <a-button size="small" type="primary" @click="openReview(record)">Review</a-button>
            <a-button
              size="small"
              danger
              :disabled="decisionStatus(record) === 'rejected'"
              @click="rejectSuggestion(record)"
            >
              Reject
            </a-button>
          </div>
        </template>
      </template>
    </a-table>

    <a-modal
      v-model:open="review.visible"
      title="Review alias suggestion"
      ok-text="Approve"
      :confirm-loading="review.saving"
      @ok="approveCurrent"
    >
      <a-form layout="vertical">
        <a-form-item label="Raw label">
          <a-input :value="review.record?.raw_label" disabled />
        </a-form-item>
        <a-form-item label="Canonical label">
          <a-input v-model:value="review.form.canonical_label" />
        </a-form-item>
        <a-form-item label="Canonical key">
          <a-input v-model:value="review.form.canonical_key" />
        </a-form-item>
        <a-form-item label="Concept type">
          <a-select v-model:value="review.form.concept_type">
            <a-select-option value="ResearchTopic">ResearchTopic</a-select-option>
            <a-select-option value="Domain">Domain</a-select-option>
            <a-select-option value="Method">Method</a-select-option>
            <a-select-option value="Model">Model</a-select-option>
            <a-select-option value="Dataset">Dataset</a-select-option>
            <a-select-option value="Metric">Metric</a-select-option>
            <a-select-option value="Task">Task</a-select-option>
            <a-select-option value="Result">Result</a-select-option>
            <a-select-option value="Innovation">Innovation</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Aliases">
          <a-textarea
            v-model:value="review.form.aliases_text"
            :rows="3"
            placeholder="One alias per line"
          />
        </a-form-item>
        <a-form-item label="Rationale">
          <a-textarea v-model:value="review.form.rationale" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { entityResolutionApi } from '@/apis/graph_api'

const statusFilter = ref('pending')
const suggestions = ref([])
const counts = ref({})
const paths = ref({})
const state = reactive({
  loading: false,
  syncing: false,
  exporting: false
})
const review = reactive({
  visible: false,
  saving: false,
  record: null,
  form: {
    canonical_label: '',
    canonical_key: '',
    concept_type: 'ResearchTopic',
    aliases_text: '',
    rationale: ''
  }
})

const columns = [
  { title: 'Raw Concept', key: 'raw', width: 220 },
  { title: 'Canonical Target', key: 'canonical', width: 260 },
  { title: 'Status', key: 'status', width: 190 },
  { title: 'Confidence', key: 'confidence', width: 120 },
  { title: 'Aliases', key: 'aliases' },
  { title: 'Actions', key: 'actions', width: 170 }
]

const pathMessage = computed(() => {
  const exportPath = paths.value.export_path || 'not exported yet'
  return `Approved aliases are exported to: ${exportPath}`
})

const decisionStatus = (record) => record?.decision?.status || 'pending'
const statusColor = (record) => {
  const status = decisionStatus(record)
  if (status === 'approved') return 'green'
  if (status === 'rejected') return 'red'
  return 'gold'
}
const formatConfidence = (value) => {
  const numeric = Number(value || 0)
  return `${Math.round(numeric * 100)}%`
}
const displayCanonical = (record) =>
  record?.decision?.canonical_label || record?.suggested_canonical_label || record?.raw_label || '-'
const displayCanonicalKey = (record) =>
  record?.decision?.canonical_key || record?.suggested_canonical_key || ''
const previewAliases = (record) => {
  const aliases = record?.decision?.aliases || record?.aliases || []
  return aliases.slice(0, 6)
}

const loadSuggestions = async () => {
  state.loading = true
  try {
    const response = await entityResolutionApi.listSuggestions(statusFilter.value)
    const data = response.data || {}
    suggestions.value = data.items || []
    counts.value = data.counts || {}
    paths.value = data
  } catch (error) {
    console.error(error)
    message.error(error.message || 'Failed to load alias suggestions')
  } finally {
    state.loading = false
  }
}

const syncSuggestions = async () => {
  state.syncing = true
  try {
    const response = await entityResolutionApi.syncSuggestions()
    const data = response.data || {}
    if (data.missing_source) {
      message.warning('Suggestion source file was not found')
    } else {
      message.success(`Synced ${data.imported} new and ${data.updated} existing suggestions`)
    }
    await loadSuggestions()
  } catch (error) {
    console.error(error)
    message.error(error.message || 'Failed to sync suggestions')
  } finally {
    state.syncing = false
  }
}

const openReview = (record) => {
  review.record = record
  review.form.canonical_label = displayCanonical(record)
  review.form.canonical_key = displayCanonicalKey(record)
  review.form.concept_type = record?.decision?.concept_type || record?.concept_type || 'ResearchTopic'
  review.form.aliases_text = previewAliases(record).join('\n')
  review.form.rationale = record?.decision?.rationale || record?.rationale || ''
  review.visible = true
}

const approveCurrent = async () => {
  if (!review.record) return
  if (!review.form.canonical_label.trim()) {
    message.warning('Canonical label is required')
    return
  }
  review.saving = true
  try {
    await entityResolutionApi.approveSuggestion(review.record.id, {
      canonical_label: review.form.canonical_label,
      canonical_key: review.form.canonical_key,
      concept_type: review.form.concept_type,
      aliases: review.form.aliases_text.split('\n').map((item) => item.trim()).filter(Boolean),
      rationale: review.form.rationale
    })
    message.success('Alias suggestion approved')
    review.visible = false
    await loadSuggestions()
  } catch (error) {
    console.error(error)
    message.error(error.message || 'Failed to approve alias suggestion')
  } finally {
    review.saving = false
  }
}

const rejectSuggestion = (record) => {
  Modal.confirm({
    title: 'Reject alias suggestion?',
    content: `Raw concept: ${record.raw_label}`,
    okText: 'Reject',
    okType: 'danger',
    async onOk() {
      await entityResolutionApi.rejectSuggestion(record.id, 'Rejected from UI review')
      message.success('Alias suggestion rejected')
      await loadSuggestions()
    }
  })
}

const exportAliases = async () => {
  state.exporting = true
  try {
    const response = await entityResolutionApi.exportApprovedAliases()
    const data = response.data || {}
    message.success(`Exported ${data.approved_count || 0} approved aliases`)
    paths.value.export_path = data.export_path
  } catch (error) {
    console.error(error)
    message.error(error.message || 'Failed to export aliases')
  } finally {
    state.exporting = false
  }
}

onMounted(loadSuggestions)
</script>

<style scoped lang="less">
.alias-curation {
  height: calc(100vh - 50px);
  overflow: auto;
  padding: 20px 24px;
  background: var(--gray-0);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.summary,
.actions,
.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-item {
  min-width: 104px;
  padding: 10px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
}

.summary-label {
  display: block;
  margin-bottom: 4px;
  color: var(--gray-700);
  font-size: 12px;
}

.path-note {
  margin-bottom: 12px;
}

.raw-cell,
.canonical-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.raw-cell span,
.canonical-cell code {
  color: var(--gray-700);
  font-size: 12px;
}

.alias-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
