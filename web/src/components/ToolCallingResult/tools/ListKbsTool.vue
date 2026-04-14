<template>
  <BaseToolCall :tool-call="toolCall" :hide-params="true">
    <template #header>
      <div class="sep-header">
        <span class="note">{{ operationLabel }}</span>
        <span class="separator">|</span>
        <span class="description">{{ headerSummary }}</span>
      </div>
    </template>
    <template #result="{}">
      <div class="list-kbs-result">
        <div class="kb-count">Total {{ kbList.length }} knowledge bases</div>
        <div class="kb-list">
          <div v-for="kb in kbList" :key="kb.name" class="kb-item">
            <div class="kb-name">{{ kb.name }}</div>
            <div class="kb-description">{{ kb.description || 'No description' }}</div>
          </div>
        </div>
      </div>
    </template>
  </BaseToolCall>
</template>

<script setup>
import { computed } from 'vue'
import BaseToolCall from '../BaseToolCall.vue'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  }
})

const toolName = computed(
  () => props.toolCall.name || props.toolCall.function?.name || 'Knowledge Base'
)

const operationLabel = computed(() => `${toolName.value} List`)

const parseData = (content) => {
  if (typeof content === 'string') {
    try {
      return JSON.parse(content)
    } catch {
      return []
    }
  }
  return content || []
}

const kbList = computed(() => {
  const resultContent = props.toolCall.tool_call_result?.content
  const data = parseData(resultContent)
  return Array.isArray(data) ? data : []
})

const headerSummary = computed(() => {
  const names = kbList.value.map((kb) => kb?.name).filter(Boolean)
  if (!names.length) return 'No knowledge bases'

  const previewNames = names.slice(0, 3).join(', ')
  const remainingCount = names.length - 3
  return remainingCount > 0
    ? `${names.length} knowledge bases: ${previewNames} and ${remainingCount} more`
    : `${names.length} knowledge bases: ${previewNames}`
})
</script>

<style scoped lang="less">
.list-kbs-result {
  background: var(--gray-0);
  border-radius: 8px;
  padding: 12px 16px;

  .kb-count {
    font-size: 12px;
    color: var(--gray-700);
    margin-bottom: 12px;
  }

  .kb-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .kb-item {
    padding: 10px 12px;
    background: var(--gray-10);
    border-radius: 6px;
    border: 1px solid var(--gray-100);

    .kb-name {
      font-size: 13px;
      font-weight: 500;
      color: var(--gray-700);
      margin-bottom: 4px;
    }

    .kb-description {
      font-size: 12px;
      color: var(--gray-600);
    }
  }
}
</style>
