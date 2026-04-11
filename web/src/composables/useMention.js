import { ref } from 'vue'

/**
 * @typedef {Object} MentionFile
 * @property {string} path - File path
 * @property {string} [content] - File content
 * @property {string} [modified_at] - Modified time
 * @property {number} [size] - File size
 */

/**
 * @typedef {Object} MentionKnowledgeBase
 * @property {string} db_id - Knowledge base ID
 * @property {string} name - Knowledge base name
 */

/**
 * @typedef {Object} MentionMcp
 * @property {string} name - MCP name
 * @property {string} [description] - Description
 */

/**
 * @typedef {Object} MentionConfig
 * @property {MentionFile[]} [files] - Referenceable file list
 * @property {MentionKnowledgeBase[]} [knowledgeBases] - Referenceable knowledge base list
 * @property {MentionMcp[]} [mcps] - Referenceable MCP server list
 */

/**
 * @typedef {Object} MentionItem
 * @property {string} value - Displayed and inserted value
 * @property {string} label - Display label
 * @property {'file'|'knowledge'|'mcp'} type - Type
 * @property {string} [description] - Description
 */

/**
 * @typedef {Object} UseMentionReturn
 * @property {import('vue').Ref<MentionConfig>} mentionConfig - Current mention configuration
 * @property {Function} setMention - Set mention configuration
 * @property {Function} updateFiles - Update file list
 * @property {Function} updateKnowledgeBases - Update knowledge base list
 * @property {Function} updateMcps - Update MCP list
 * @property {Function} getFilteredItems - Get filtered candidates for a query
 */

/**
 * Mention @ mention management
 * @returns {UseMentionReturn}
 */
export function useMention() {
  const mentionConfig = ref({
    files: [],
    knowledgeBases: [],
    mcps: []
  })

  /**
  * Set the full mention configuration
   * @param {MentionConfig} config
   */
  const setMention = (config) => {
    mentionConfig.value = {
      files: config.files || [],
      knowledgeBases: config.knowledgeBases || [],
      mcps: config.mcps || []
    }
  }

  /**
  * Update the file list
   * @param {MentionFile[]} files
   */
  const updateFiles = (files) => {
    mentionConfig.value.files = files || []
  }

  /**
  * Update the knowledge base list
   * @param {MentionKnowledgeBase[]} knowledgeBases
   */
  const updateKnowledgeBases = (knowledgeBases) => {
    mentionConfig.value.knowledgeBases = knowledgeBases || []
  }

  /**
  * Update the MCP server list
   * @param {MentionMcp[]} mcps
   */
  const updateMcps = (mcps) => {
    mentionConfig.value.mcps = mcps || []
  }

  /**
  * Get all categorized candidates
   * @returns {{ files: MentionItem[], knowledgeBases: MentionItem[], mcps: MentionItem[] }}
   */
  const getCategorizedItems = () => {
    const { files, knowledgeBases, mcps } = mentionConfig.value

    const fileItems = files.map((f) => ({
      value: f.path,
      label: f.path.split('/').pop() || f.path,
      type: 'file',
      description: f.path
    }))

    const kbItems = knowledgeBases.map((kb) => ({
      value: kb.name,
      label: kb.name,
      type: 'knowledge',
      description: kb.db_id
    }))

    const mcpItems = mcps.map((m) => ({
      value: m.name,
      label: m.name,
      type: 'mcp',
      description: m.description || ''
    }))

    return {
      files: fileItems,
      knowledgeBases: kbItems,
      mcps: mcpItems
    }
  }

  /**
  * Filter candidates by query string
  * @param {string} query - Query string (without the @ symbol)
   * @returns {{ files: MentionItem[], knowledgeBases: MentionItem[], mcps: MentionItem[] }}
   */
  const getFilteredItems = (query = '') => {
    const lowerQuery = query.toLowerCase()
    const categorized = getCategorizedItems()

    const filterItems = (items) =>
      items.filter(
        (item) =>
          item.label.toLowerCase().includes(lowerQuery) ||
          item.value.toLowerCase().includes(lowerQuery)
      )

    return {
      files: filterItems(categorized.files),
      knowledgeBases: filterItems(categorized.knowledgeBases),
      mcps: filterItems(categorized.mcps)
    }
  }

  return {
    mentionConfig,
    setMention,
    updateFiles,
    updateKnowledgeBases,
    updateMcps,
    getFilteredItems,
    getCategorizedItems
  }
}
