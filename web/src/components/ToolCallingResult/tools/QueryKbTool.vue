<template>
  <BaseToolCall :tool-call="toolCall" :hide-params="true">
    <template #header>
      <div class="sep-header">
        <span class="note">{{ operationLabel }}</span>
        <span class="separator" v-if="kbName">|</span>
        <span class="description" v-if="kbName">Knowledge Base: {{ kbName }}</span>
        <span class="separator" v-if="queryText">|</span>
        <span class="description">{{ queryText }}</span>
      </div>
    </template>
    <template #result="{ resultContent }">
      <div class="query-kb-result">
        <KbResultGroupedList
          :chunks="extractChunks(resultContent)"
          :academic-retrieval="extractAcademicRetrieval(resultContent)"
          :graph="extractGraph(resultContent)"
          :grounding="extractGrounding(resultContent)"
          :evidence-summary="extractSummary(resultContent)"
          :raw-text="extractRawText(resultContent)"
        />
      </div>
    </template>
  </BaseToolCall>
</template>

<script setup>
import { computed, inject, ref } from 'vue'
import BaseToolCall from '../BaseToolCall.vue'
import KbResultGroupedList from '@/components/sources/KbResultGroupedList.vue'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  }
})

const agentStateFiles = inject('agentStateFiles', ref({}))

const args = computed(() => {
  const value = props.toolCall.args || props.toolCall.function?.arguments
  if (!value) return {}
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
})

const toolName = computed(
  () => props.toolCall.name || props.toolCall.function?.name || 'Knowledge Base'
)

const operationLabel = computed(() => `${toolName.value} Search`)

const kbName = computed(() => args.value.kb_name || '')
const queryText = computed(() => args.value.query_text || '')

const getRealContent = (content) => {
  if (typeof content === 'string' && content.includes('[ToolResultOffloaded]')) {
    const match = content.match(/File path:\s*([^\s\n\r]+)/)
    if (match && match[1]) {
      const filePath = match[1].trim()
      const fileData = agentStateFiles.value[filePath]
      if (fileData) {
        const rawText = Array.isArray(fileData.content)
          ? fileData.content.join('')
          : (fileData.content || '')
        
        const braceIndex = rawText.indexOf('{')
        const bracketIndex = rawText.indexOf('[')
        let startIndex = -1
        if (braceIndex !== -1 && bracketIndex !== -1) {
          startIndex = Math.min(braceIndex, bracketIndex)
        } else {
          startIndex = braceIndex !== -1 ? braceIndex : bracketIndex
        }
        
        if (startIndex !== -1) {
          return rawText.substring(startIndex)
        }
        return rawText
      }
    }
  }
  return content
}

const parseData = (content) => {
  const realContent = getRealContent(content)
  if (typeof realContent === 'string') {
    try {
      return JSON.parse(realContent)
    } catch {
      return { rawText: realContent }
    }
  }
  return realContent || []
}

const extractChunks = (content) => {
  const data = parseData(content)
  if (Array.isArray(data)) return data
  return Array.isArray(data?.chunks) ? data.chunks : []
}

const extractAcademicRetrieval = (content) => {
  const data = parseData(content)
  return data && typeof data === 'object' && !Array.isArray(data) ? data.academic_retrieval || {} : {}
}

const extractGraph = (content) => {
  const data = parseData(content)
  return data && typeof data === 'object' && !Array.isArray(data) ? data.graph || {} : {}
}

const extractGrounding = (content) => {
  const data = parseData(content)
  return data && typeof data === 'object' && !Array.isArray(data) ? data.grounding || {} : {}
}

const extractSummary = (content) => {
  const data = parseData(content)
  return data && typeof data === 'object' && !Array.isArray(data) ? data.summary || '' : ''
}

const extractRawText = (content) => {
  const data = parseData(content)
  return data && typeof data === 'object' && !Array.isArray(data) ? data.rawText || '' : ''
}
</script>

<style scoped lang="less">
.query-kb-result {
  background: var(--gray-0);
  border-radius: 8px;
  padding: 4px;
}
</style>
