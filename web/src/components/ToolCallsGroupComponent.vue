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
import { computed, ref, watch } from 'vue'
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
  }
})

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
