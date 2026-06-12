import {
  BookOpen,
  CheckSquare,
  FileEdit,
  FilePen,
  FileText,
  Folder,
  FolderSearch,
  Globe,
  HelpCircle,
  Network,
  Terminal
} from 'lucide-vue-next'

export const TOOL_ICON_MAP = {
  ask_user_question: HelpCircle,
  bash: Terminal,
  cmd: Terminal,
  edit_file: FilePen,
  execute: Terminal,
  get_mindmap: Network,
  glob: FolderSearch,
  grep: FolderSearch,
  list_directory: Folder,
  list_kbs: BookOpen,
  ls: Folder,
  query_kb: BookOpen,
  query_knowledge_graph: Network,
  read_file: FileText,
  replace: FilePen,
  run_shell_command: Terminal,
  search_file_content: FolderSearch,
  tavily_search: Globe,
  write_file: FileEdit,
  write_todos: CheckSquare
}

export const getToolCallId = (toolCall) => toolCall?.name || toolCall?.function?.name || ''

export const HIDDEN_TOOL_CALL_IDS = []

export const isHiddenToolCall = (toolCall) => HIDDEN_TOOL_CALL_IDS.includes(getToolCallId(toolCall))

export const isValidToolCall = (toolCall) => {
  return Boolean(
    toolCall &&
      (toolCall.id || toolCall.name || toolCall.function?.name) &&
      (toolCall.args !== undefined ||
        toolCall.function?.arguments !== undefined ||
        toolCall.tool_call_result !== undefined)
  )
}

export const parseToolCallArgs = (toolCall) => {
  const args = toolCall?.args ?? toolCall?.function?.arguments
  if (!args) return {}
  if (typeof args === 'object') return args
  try {
    return JSON.parse(args)
  } catch {
    return {}
  }
}

export const normalizeToolCalls = (toolCalls, { includeHidden = false, mapToolCall } = {}) => {
  if (!Array.isArray(toolCalls)) return []

  return toolCalls
    .filter((toolCall) => {
      if (!isValidToolCall(toolCall)) return false
      return includeHidden || !isHiddenToolCall(toolCall)
    })
    .map((toolCall) => (mapToolCall ? mapToolCall(toolCall) : toolCall))
}

export const enrichTaskToolCalls = (toolCalls, options = {}) =>
  normalizeToolCalls(toolCalls, options)

export const getToolIcon = (toolId) => TOOL_ICON_MAP[toolId] || null
