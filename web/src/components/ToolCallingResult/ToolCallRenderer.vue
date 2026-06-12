<template>
  <component
    :is="currentRenderer"
    v-if="currentRenderer"
    :tool-call="toolCall"
    :appearance="appearance"
    :default-expanded="defaultExpanded"
    ref="toolRendererRef"
  />
  <BaseToolCall
    v-else-if="!isHidden"
    :tool-call="toolCall"
    :appearance="appearance"
    :default-expanded="defaultExpanded"
  />
</template>

<script setup>
import { computed, ref } from 'vue'
import BaseToolCall from './BaseToolCall.vue'

import WebSearchTool from './tools/WebSearchTool.vue'
import ListKbsTool from './tools/ListKbsTool.vue'
import GetMindmapTool from './tools/GetMindmapTool.vue'
import QueryKbTool from './tools/QueryKbTool.vue'
import KnowledgeGraphTool from './tools/KnowledgeGraphTool.vue'
import TodoListTool from './tools/TodoListTool.vue'
import WriteFileTool from './tools/WriteFileTool.vue'
import ReadFileTool from './tools/ReadFileTool.vue'
import ListDirectoryTool from './tools/ListDirectoryTool.vue'
import SearchFileContentTool from './tools/SearchFileContentTool.vue'
import GrepTool from './tools/GrepTool.vue'
import GlobTool from './tools/GlobTool.vue'
import EditFileTool from './tools/EditFileTool.vue'
import AskUserQuestionTool from './tools/AskUserQuestionTool.vue'
import ExecuteTool from './tools/ExecuteTool.vue'
import { getToolCallId } from './toolRegistry'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  appearance: {
    type: String,
    default: 'card'
  },
  defaultExpanded: {
    type: Boolean,
    default: false
  }
})

const toolId = computed(() => getToolCallId(props.toolCall))

const TOOL_RENDERERS = {
  ask_user_question: AskUserQuestionTool,
  bash: ExecuteTool,
  cmd: ExecuteTool,
  edit_file: EditFileTool,
  execute: ExecuteTool,
  get_mindmap: GetMindmapTool,
  glob: GlobTool,
  grep: GrepTool,
  list_directory: ListDirectoryTool,
  list_kbs: ListKbsTool,
  ls: ListDirectoryTool,
  query_kb: QueryKbTool,
  query_knowledge_graph: KnowledgeGraphTool,
  read_file: ReadFileTool,
  replace: EditFileTool,
  run_shell_command: ExecuteTool,
  search_file_content: SearchFileContentTool,
  tavily_search: WebSearchTool,
  write_file: WriteFileTool,
  write_todos: TodoListTool
}

const TOOL_RENDERER_HIDE = []

const currentRenderer = computed(() => TOOL_RENDERERS[toolId.value] || null)
const isHidden = computed(() => TOOL_RENDERER_HIDE.includes(toolId.value))

const toolRendererRef = ref(null)
const refreshGraph = () => {
  if (toolRendererRef.value && typeof toolRendererRef.value.refreshGraph === 'function') {
    toolRendererRef.value.refreshGraph()
  }
}

defineExpose({ refreshGraph })
</script>

<style lang="less" scoped></style>
