<template>
  <div v-if="normalizedToolCalls.length > 0" class="tool-calls-container">
    <button
      type="button"
      class="tool-calls-summary"
      :class="{ 'is-expanded': areToolCallsExpanded }"
      :aria-expanded="areToolCallsExpanded"
      @click="toggleToolCallsExpanded"
    >
      <span class="summary-leading">
        <Wrench size="14" />
      </span>
      <span class="summary-content">
        <span class="summary-title">{{ toolCallsSummaryTitle }}</span>
        <span class="summary-separator" v-if="normalizedToolCalls.length > 1 && toolCallsNamesMeta"
          >-</span
        >
        <span class="summary-meta" v-if="normalizedToolCalls.length > 1 && toolCallsNamesMeta">{{
          toolCallsNamesMeta
        }}</span>
        <span class="summary-status-tag" v-if="statusSummary">{{ statusSummary }}</span>
        <span class="summary-intent-badge" v-if="detectedIntent">
          📍 Intent: {{ formatIntent(detectedIntent) }}
        </span>
        <span class="summary-sub-intents-badge" v-if="subIntents && subIntents.length">
          📊 Sub: {{ subIntents.join(', ') }}
        </span>
        <span class="summary-entities-summary" v-if="entitiesSummary" :title="entitiesSummary">
          {{ entitiesSummary }}
        </span>
      </span>
      <span class="summary-trailing">
        <component :is="areToolCallsExpanded ? ChevronDown : ChevronRight" size="14" />
      </span>
    </button>

    <div v-if="areToolCallsExpanded" class="tool-calls-panel">
      <div
        v-for="(toolCall, index) in normalizedToolCalls"
        :key="toolCall.id || `${getToolCallId(toolCall)}-${index}`"
        class="tool-call-container"
      >
        <ToolCallRenderer :tool-call="toolCall" :default-expanded="false" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, inject } from 'vue'
import { ChevronDown, ChevronRight, Wrench } from 'lucide-vue-next'
import { ToolCallRenderer } from '@/components/ToolCallingResult'
import { getToolCallId, normalizeToolCalls } from '@/components/ToolCallingResult/toolRegistry'

const props = defineProps({
  toolCalls: {
    type: Array,
    default: () => []
  },
  isActive: {
    type: Boolean,
    default: false
  },
  conv: {
    type: Object,
    default: null
  }
})

const liveMetadata = inject('routingMetadata', ref({}))

const detectedIntent = computed(() => {
  if (props.conv && Array.isArray(props.conv.messages)) {
    const aiMsg = props.conv.messages.find((msg) => msg.type === 'ai' || msg.role === 'assistant')
    if (aiMsg?.extra_metadata?.routing_metadata?.detected_intent) {
      return aiMsg.extra_metadata.routing_metadata.detected_intent
    }
  }
  return liveMetadata.value?.detected_intent || null
})

const subIntents = computed(() => {
  if (props.conv && Array.isArray(props.conv.messages)) {
    const aiMsg = props.conv.messages.find((msg) => msg.type === 'ai' || msg.role === 'assistant')
    if (aiMsg?.extra_metadata?.routing_metadata?.sub_intents) {
      return aiMsg.extra_metadata.routing_metadata.sub_intents
    }
  }
  return liveMetadata.value?.sub_intents || []
})

const extractedEntities = computed(() => {
  if (props.conv && Array.isArray(props.conv.messages)) {
    const aiMsg = props.conv.messages.find((msg) => msg.type === 'ai' || msg.role === 'assistant')
    if (aiMsg?.extra_metadata?.routing_metadata?.entities) {
      return aiMsg.extra_metadata.routing_metadata.entities
    }
  }
  return liveMetadata.value?.entities || {}
})

const entitiesSummary = computed(() => {
  const ent = extractedEntities.value
  if (!ent) return ''
  const summary = []
  if (Array.isArray(ent.author_names) && ent.author_names.length) {
    summary.push(`👤 ${ent.author_names.join(', ')}`)
  }
  if (ent.department) {
    summary.push(`🏫 ${ent.department}`)
  }
  if (Array.isArray(ent.topics) && ent.topics.length) {
    const topicsToShow = ent.topics.map(t => t.length > 20 ? t.slice(0, 17) + '...' : t)
    summary.push(`📚 ${topicsToShow.join(', ')}`)
  }
  if (ent.publication_title) {
    const title = ent.publication_title
    summary.push(`📄 ${title.length > 25 ? title.slice(0, 22) + '...' : title}`)
  }
  return summary.join(' | ')
})

const formatIntent = (intent) => {
  if (!intent) return ''
  const mapping = {
    graph_search: 'Graph Search',
    vector_search: 'Vector Search',
    hybrid_search: 'Hybrid Search'
  }
  return mapping[intent] || intent
}

const normalizedToolCalls = computed(() => normalizeToolCalls(props.toolCalls))
const areToolCallsExpanded = ref(false)

watch(
  [() => normalizedToolCalls.value.length, () => props.isActive],
  ([, isActive], [, previousActive]) => {
    if (isActive) {
      areToolCallsExpanded.value = true
      return
    }
    if (previousActive === true && isActive === false) {
      areToolCallsExpanded.value = false
      return
    }
    if (!previousActive && !isActive) {
      areToolCallsExpanded.value = false
    }
  },
  { immediate: true }
)

const getToolCallLabel = (toolCall) => {
  const displayLabel = String(toolCall?.display_label || '').trim()
  if (displayLabel) return displayLabel

  const rawName = getToolCallId(toolCall)
  const name = typeof rawName === 'string' ? rawName.replaceAll('_', ' ') : 'tool'
  return name.charAt(0).toUpperCase() + name.slice(1)
}

const toolCallsSummaryTitle = computed(() => {
  if (normalizedToolCalls.value.length === 1) {
    return `Using tool: ${getToolCallLabel(normalizedToolCalls.value[0])}`
  }
  return `Used ${normalizedToolCalls.value.length} tools`
})

const toolCallsNamesMeta = computed(() => {
  const names = normalizedToolCalls.value.map(getToolCallLabel).filter(Boolean)
  const uniqueNames = [...new Set(names)]
  const visibleNames = uniqueNames.slice(0, 3)
  if (visibleNames.length === 0) return ''
  return `${visibleNames.join(' - ')}${uniqueNames.length > visibleNames.length ? ` +${uniqueNames.length - visibleNames.length}` : ''}`
})

const toolRunState = (toolCall) => {
  if (toolCall.status === 'error') return 'error'
  if (toolCall.tool_call_result || toolCall.status === 'success') return 'completed'
  return 'running'
}

const statusSummary = computed(() => {
  const states = normalizedToolCalls.value.map(toolRunState)
  const successCount = states.filter((state) => state === 'completed').length
  const runningCount = states.filter((state) => state === 'running').length
  const errorCount = states.filter((state) => state === 'error').length

  if (successCount > 0 && successCount === normalizedToolCalls.value.length) {
    return 'Completed'
  }
  const parts = []
  if (errorCount > 0) parts.push(`${errorCount} failed`)
  if (runningCount > 0) parts.push(`${runningCount} running`)
  return parts.join(' - ')
})

const toggleToolCallsExpanded = () => {
  areToolCallsExpanded.value = !areToolCallsExpanded.value
}
</script>

<style lang="less" scoped>
.tool-calls-container {
  width: 100%;
  padding: 0;

  .tool-calls-summary {
    appearance: none;
    width: auto;
    max-width: 100%;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--gray-700);
    text-align: left;
    cursor: pointer;
    outline: none;
    border: none;
    padding: 0;
    transition: all 0.2s ease;
    user-select: none;
    background: transparent;

    &:hover {
      color: var(--gray-800);
    }

    &.is-expanded {
      color: var(--gray-800);
      margin-bottom: 4px;
    }
  }

  .summary-leading,
  .summary-trailing {
    display: inline-flex;
    align-items: center;
    color: var(--gray-600);
    flex-shrink: 0;
  }

  .summary-content {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    font-size: 13px;
    flex-wrap: wrap;
    row-gap: 4px;
  }

  .summary-title {
    font-weight: 400;
    white-space: nowrap;
  }

  .summary-separator {
    color: var(--gray-500);
    flex-shrink: 0;
  }

  .summary-meta {
    color: var(--gray-600);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .summary-status-tag {
    margin-left: 4px;
    font-size: 11px;
    padding: 0 4px;
    background: var(--gray-25);
    color: var(--gray-600);
    border-radius: 4px;
    white-space: nowrap;
    font-weight: normal;
  }

  .summary-intent-badge {
    margin-left: 8px;
    font-size: 11px;
    padding: 1px 6px;
    background: rgba(37, 99, 235, 0.08);
    color: var(--main-600, #2563eb);
    border: 1px solid rgba(37, 99, 235, 0.15);
    border-radius: 4px;
    font-weight: 500;
    white-space: nowrap;
  }

  .summary-sub-intents-badge {
    margin-left: 4px;
    font-size: 11px;
    padding: 1px 6px;
    background: rgba(16, 185, 129, 0.08);
    color: #10b981;
    border: 1px solid rgba(16, 185, 129, 0.15);
    border-radius: 4px;
    font-weight: 500;
    white-space: nowrap;
  }

  .summary-entities-summary {
    margin-left: 8px;
    font-size: 11px;
    color: var(--gray-600);
    background: var(--gray-25);
    padding: 1px 6px;
    border-radius: 4px;
    border: 1px solid var(--gray-100);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 300px;
  }

  .tool-calls-panel {
    border-top: 1px solid var(--gray-100);
    padding-top: 4px;
    margin-top: 4px;
    margin-bottom: 8px;
  }

  .tool-call-container {
    margin-bottom: 4px;

    &:last-child {
      margin-bottom: 0;
    }
  }
}
</style>
