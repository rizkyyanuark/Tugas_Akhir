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

export const getToolIcon = (toolId) => TOOL_ICON_MAP[toolId] || null
