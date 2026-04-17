/**
 * Message processing utility class
 */
export class MessageProcessor {
  /**
   * Merge tool results into messages
   * @param {Array} msgs - Message array
   * @returns {Array} Merged message array
   */
  static convertToolResultToMessages(msgs) {
    const toolResponseMap = new Map()

    // Build a map of tool responses
    for (const item of msgs) {
      if (item.type === 'tool') {
        // Match tool calls using multiple possible ID fields
        const toolCallId = item.tool_call_id || item.id
        if (toolCallId) {
          toolResponseMap.set(toolCallId, item)
        }
      }
    }

    // Merge tool calls and responses
    const convertedMsgs = msgs.map((item) => {
      if (item.type === 'ai' && item.tool_calls && item.tool_calls.length > 0) {
        return {
          ...item,
          tool_calls: item.tool_calls.map((toolCall) => {
            const toolResponse = toolResponseMap.get(toolCall.id)
            return {
              ...toolCall,
              tool_call_result: toolResponse || null
            }
          })
        }
      }
      return item
    })

    return convertedMsgs
  }

  /**
   * Convert server history into conversation format
   * @param {Array} serverHistory - Server history
   * @returns {Array} Conversation array
   */
  static convertServerHistoryToMessages(serverHistory) {
    // Filter out standalone 'tool' messages since tool results are already in AI messages' tool_calls
    // Backend new storage: tool results are embedded in AI messages' tool_calls array with tool_call_result field
    const filteredHistory = serverHistory.filter((item) => item.type !== 'tool')

    // Group by conversation
    const conversations = []
    let currentConv = null

    for (const item of filteredHistory) {
      if (item.type === 'human') {
        // Start a new conversation and finalize the previous one
        if (currentConv) {
          // Find the last AI message and mark it as final
          for (let i = currentConv.messages.length - 1; i >= 0; i--) {
            if (currentConv.messages[i].type === 'ai') {
              currentConv.messages[i].isLast = true
              currentConv.status = 'finished'
              break
            }
          }
        }
        currentConv = {
          messages: [item],
          status: 'loading'
        }
        conversations.push(currentConv)
      } else if (item.type === 'ai' && currentConv) {
        currentConv.messages.push(item)
      }
    }

    // Mark the last conversation as finished
    if (currentConv && currentConv.messages.length > 0) {
      // Find the last AI message and mark it as final
      for (let i = currentConv.messages.length - 1; i >= 0; i--) {
        if (currentConv.messages[i].type === 'ai') {
          currentConv.messages[i].isLast = true
          currentConv.status = 'finished'
          break
        }
      }
    }

    return conversations
  }

  /**
   * Extract all knowledge base retrieval chunks from a conversation round
   * @param {Object} conv - Single conversation
   * @param {Array} databases - Knowledge base list
   * @returns {Array} Normalized retrieval chunks
   */
  static extractKnowledgeChunksFromConversation(conv, databases = []) {
    if (!conv || !Array.isArray(conv.messages) || conv.messages.length === 0) return []

    const databaseNames = new Set(
      (databases || [])
        .map((db) => db?.name)
        .filter((name) => typeof name === 'string' && name.trim())
    )
    if (databaseNames.size === 0) return []

    const normalizedChunks = []
    const dedupSet = new Set()

    const appendChunk = (chunk, kbName) => {
      if (!chunk || typeof chunk !== 'object') return
      const content = typeof chunk.content === 'string' ? chunk.content.trim() : ''
      if (!content) return

      const metadata = chunk.metadata && typeof chunk.metadata === 'object' ? chunk.metadata : {}
      const dedupKey =
        metadata.chunk_id && typeof metadata.chunk_id === 'string'
          ? `${kbName}::${metadata.chunk_id}`
          : `${kbName}::${content}`
      if (dedupSet.has(dedupKey)) return
      dedupSet.add(dedupKey)

      const score = typeof chunk.score === 'number' ? chunk.score : null
      normalizedChunks.push({
        kb_name: kbName,
        content,
        score,
        metadata: {
          source: metadata.source || '',
          file_id: metadata.file_id || '',
          chunk_id: metadata.chunk_id || '',
          chunk_index: metadata.chunk_index
        }
      })
    }

    const parseToolResultContent = (content) => {
      if (Array.isArray(content)) return content
      if (content && typeof content === 'object') return content
      if (typeof content === 'string') {
        try {
          return JSON.parse(content)
        } catch {
          return null
        }
      }
      return null
    }

    for (const msg of conv.messages) {
      if (!msg || msg.type !== 'ai' || !Array.isArray(msg.tool_calls)) continue

      for (const toolCall of msg.tool_calls) {
        const kbName = toolCall?.name || toolCall?.function?.name
        if (!databaseNames.has(kbName)) continue

        const content = toolCall?.tool_call_result?.content
        const parsed = parseToolResultContent(content)
        if (!parsed) continue

        // Milvus / Dify: direct chunks array
        if (Array.isArray(parsed)) {
          for (const chunk of parsed) appendChunk(chunk, kbName)
          continue
        }

        // LightRAG: result is an object, chunks are under data.chunks
        const lightragChunks = parsed?.data?.chunks
        if (Array.isArray(lightragChunks)) {
          for (const chunk of lightragChunks) appendChunk(chunk, kbName)
        }
      }
    }

    normalizedChunks.sort((a, b) => {
      const scoreA = typeof a.score === 'number' ? a.score : Number.NEGATIVE_INFINITY
      const scoreB = typeof b.score === 'number' ? b.score : Number.NEGATIVE_INFINITY
      return scoreB - scoreA
    })

    return normalizedChunks
  }

  /**
   * Extract web search sources from a conversation round
   * @param {Object} conv - Single conversation
   * @returns {Array} Normalized web sources
   */
  static extractWebSourcesFromConversation(conv) {
    if (!conv || !Array.isArray(conv.messages) || conv.messages.length === 0) return []

    const webSources = []
    const dedupSet = new Set()

    const parseToolResultContent = (content) => {
      if (Array.isArray(content)) return content
      if (content && typeof content === 'object') return content
      if (typeof content === 'string') {
        try {
          return JSON.parse(content)
        } catch {
          return null
        }
      }
      return null
    }

    for (const msg of conv.messages) {
      if (!msg || msg.type !== 'ai' || !Array.isArray(msg.tool_calls)) continue

      for (const toolCall of msg.tool_calls) {
        const toolName = (toolCall?.name || toolCall?.function?.name || '').toLowerCase()
        if (!toolName.includes('tavily_search')) continue

        const content = toolCall?.tool_call_result?.content
        const parsed = parseToolResultContent(content)
        const results = Array.isArray(parsed?.results) ? parsed.results : []
        if (results.length === 0) continue

        for (const item of results) {
          const title = typeof item?.title === 'string' ? item.title.trim() : ''
          const url = typeof item?.url === 'string' ? item.url.trim() : ''
          if (!title || !url) continue
          if (dedupSet.has(url)) continue
          dedupSet.add(url)

          webSources.push({
            tool_name: toolCall?.name || toolCall?.function?.name || 'Web search',
            title,
            url,
            score: typeof item?.score === 'number' ? item.score : null,
            content: typeof item?.content === 'string' ? item.content : '',
            published_date: typeof item?.published_date === 'string' ? item.published_date : ''
          })
        }
      }
    }

    webSources.sort((a, b) => {
      const scoreA = typeof a.score === 'number' ? a.score : Number.NEGATIVE_INFINITY
      const scoreB = typeof b.score === 'number' ? b.score : Number.NEGATIVE_INFINITY
      return scoreB - scoreA
    })

    return webSources
  }

  /**
   * Extract sources from a single message
   * @param {Object} message - Message object
   * @param {Array} databases - Knowledge base list
   * @returns {{knowledgeChunks: Array, webSources: Array}}
   */
  static extractSourcesFromMessage(message, databases = []) {
    if (!message || message.type !== 'ai') return { knowledgeChunks: [], webSources: [] }

    // Reuse the extraction logic by constructing a temporary conversation object
    const mockConv = { messages: [message] }
    return {
      knowledgeChunks: MessageProcessor.extractKnowledgeChunksFromConversation(mockConv, databases),
      webSources: MessageProcessor.extractWebSourcesFromConversation(mockConv)
    }
  }

  /**
   * Extract all sources from a conversation turn (knowledge base + web search)
   * @param {Object} conv - Single-turn conversation
   * @param {Array} databases - Knowledge base list
   * @returns {{knowledgeChunks: Array, webSources: Array}}
   */
  static extractSourcesFromConversation(conv, databases = []) {
    return {
      knowledgeChunks: MessageProcessor.extractKnowledgeChunksFromConversation(conv, databases),
      webSources: MessageProcessor.extractWebSourcesFromConversation(conv)
    }
  }

  /**
   * Merge message chunks
   * @param {Array} chunks - Message chunk array
   * @returns {Object|null} Merged message
   */
  static mergeMessageChunk(chunks) {
    if (chunks.length === 0) return null

    // Deep copy the first chunk as the result
    const result = JSON.parse(JSON.stringify(chunks[0]))

    // Normalize user message content format to ensure plain text display
    if (result.type === 'human' || result.role === 'user') {
      // If content is an array (LangChain multimodal message), extract the text part
      if (Array.isArray(result.content)) {
        const textPart = result.content.find((item) => item.type === 'text')
        result.content = textPart ? textPart.text : ''
      } else {
        result.content = result.content || ''
      }
    } else {
      result.content = result.content || ''
    }

    // Merge subsequent chunks
    for (let i = 1; i < chunks.length; i++) {
      const chunk = chunks[i]

      // Merge content
      if (chunk.content) {
        result.content += chunk.content
      }

      // Merge reasoning_content
      if (chunk.reasoning_content) {
        if (!result.reasoning_content) {
          result.reasoning_content = ''
        }
        result.reasoning_content += chunk.reasoning_content
      }

      // Merge reasoning_content from additional_kwargs
      if (chunk.additional_kwargs?.reasoning_content) {
        if (!result.additional_kwargs) result.additional_kwargs = {}
        if (!result.additional_kwargs.reasoning_content) {
          result.additional_kwargs.reasoning_content = ''
        }
        result.additional_kwargs.reasoning_content += chunk.additional_kwargs.reasoning_content
      }

      // Merge tool_calls (handle the new data structure)
      MessageProcessor._mergeToolCalls(result, chunk)
    }

    // Handle AIMessageChunk type
    if (result.type === 'AIMessageChunk') {
      result.type = 'ai'
    }

    return result
  }

  /**
   * Merge tool calls
   * @private
   * @param {Object} result - Result object
   * @param {Object} chunk - Current chunk
   */
  static _mergeToolCalls(result, chunk) {
    if (chunk.tool_call_chunks && chunk.tool_call_chunks.length > 0) {
      // Ensure result has a tool_calls array
      if (!result.tool_calls) result.tool_calls = []

      for (const toolCallChunk of chunk.tool_call_chunks) {
        // Use index to identify the tool call (because there may be multiple tool calls)
        const existingToolCallIndex = result.tool_calls.findIndex(
          (t) => t.index === toolCallChunk.index
        )

        if (existingToolCallIndex !== -1) {
          // Merge tool calls with the same index
          const existingToolCall = result.tool_calls[existingToolCallIndex]

          // Update the name and ID if present
          if (toolCallChunk.name && !existingToolCall.function?.name) {
            if (!existingToolCall.function) existingToolCall.function = {}
            existingToolCall.function.name = toolCallChunk.name
          }

          if (toolCallChunk.id && !existingToolCall.id) {
            existingToolCall.id = toolCallChunk.id
          }

          // Merge arguments
          if (toolCallChunk.args) {
            if (!existingToolCall.function) existingToolCall.function = {}
            if (!existingToolCall.function.arguments) existingToolCall.function.arguments = ''
            existingToolCall.function.arguments += toolCallChunk.args
          }
        } else {
          // Add a new tool call
          const newToolCall = {
            index: toolCallChunk.index,
            id: toolCallChunk.id,
            function: {
              name: toolCallChunk.name || null,
              arguments: toolCallChunk.args || ''
            }
          }
          result.tool_calls.push(newToolCall)
        }
      }
    }
  }

  /**
   * Process a streaming response chunk
   * @param {Object} data - Response data
   * @param {Object} onGoingConv - In-progress conversation object
   * @param {Object} state - State object
   * @param {Function} getAgentHistory - History retrieval function
   * @param {Function} handleError - Error handler
   */
  static async processResponseChunk(data, onGoingConv, state, getAgentHistory, handleError) {
    try {
      switch (data.status) {
        case 'init':
          // Indicates the server received the request and returned the first response
          state.waitingServerResponse = false
          onGoingConv.msgChunks[data.request_id] = [data.msg]
          break

        case 'loading':
          if (data.msg.id) {
            if (!onGoingConv.msgChunks[data.msg.id]) {
              onGoingConv.msgChunks[data.msg.id] = []
            }
            onGoingConv.msgChunks[data.msg.id].push(data.msg)
          }
          break

        case 'error':
          console.error('Streaming processing error:', data.message)
          handleError(new Error(data.message), 'stream')
          break

        case 'finished':
          await getAgentHistory()
          break

        default:
          console.warn('Unknown response status:', data.status)
      }
    } catch (error) {
      handleError(error, 'stream')
    }
  }

  /**
   * Handle a streaming response
   * @param {Response} response - Response object
   * @param {Function} processChunk - Chunk processing function
   * @param {Function} scrollToBottom - Scroll-to-bottom function
   * @param {Function} handleError - Error handler
   */
  static async handleStreamResponse(response, processChunk, scrollToBottom, handleError) {
    try {
      const reader = response.body.getReader()
      let buffer = ''
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Keep the last line, which may be incomplete

        for (const line of lines) {
          if (line.trim()) {
            try {
              const data = JSON.parse(line.trim())
              await processChunk(data)
            } catch (e) {
              console.debug('JSON parse error:', e.message)
            }
          }
        }
        await scrollToBottom()
      }

      // Process any remaining content in the buffer
      if (buffer.trim()) {
        try {
          const data = JSON.parse(buffer.trim())
          await processChunk(data)
        } catch {
          console.warn('Unable to parse the final buffer content:', buffer)
        }
      }
    } catch (error) {
      handleError(error, 'stream')
    }
  }
}

export default MessageProcessor
