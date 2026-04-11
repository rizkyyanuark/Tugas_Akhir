import { marked } from 'marked'
import dayjs, { parseToShanghai } from '@/utils/time'
import chatExportTemplate from './templates/chat-export-template.html?raw'

// Unified Markdown rendering configuration
marked.setOptions({
  gfm: true,
  breaks: true,
  mangle: false,
  headerIds: false
})

export class ChatExporter {
  /**
   * Export a chat conversation as an HTML file
   * @param {Object} options Export options
   */
  static async exportToHTML(options = {}) {
    const {
      chatTitle = 'New Conversation',
      agentName = 'Smart Assistant',
      agentDescription = '',
      messages = []
    } = options || {}

    try {
      const htmlContent = this.generateHTML({
        chatTitle,
        agentName,
        agentDescription,
        messages
      })

      const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const timestamp = dayjs().tz('Asia/Shanghai').format('YYYYMMDD-HHmmss')
      const safeTitle = chatTitle.replace(/[\\/:*?"<>|]/g, '_')
      const filename = `${safeTitle}-${timestamp}.html`

      link.href = url
      link.download = filename
      link.style.display = 'none'

      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)

      return { success: true, filename }
    } catch (error) {
      console.error('Failed to export conversation:', error)
      throw new Error(`Export failed: ${error.message}`)
    }
  }

  /**
   * Generate the full HTML content
   */
  static generateHTML(options) {
    const { chatTitle, agentName, agentDescription, messages } = options

    const flattenedMessages = this.flattenMessages(messages)
    if (flattenedMessages.length === 0) {
      throw new Error('There is no conversation content to export')
    }

    const messagesHTML = this.generateMessagesHTML(flattenedMessages, agentName)

    return this.generateHTMLTemplate({
      chatTitle,
      agentName,
      agentDescription,
      exportTime: dayjs().tz('Asia/Shanghai').format('YYYY-MM-DD HH:mm:ss'),
      messagesHTML
    })
  }

  /**
   * Flatten the message list
   */
  static flattenMessages(messages = []) {
    const result = []

    console.log('[ChatExporter] flattenMessages input:', {
      messagesLength: messages?.length || 0,
      messagesType: Array.isArray(messages) ? 'array' : typeof messages,
      firstMessage: messages?.[0]
        ? {
            hasMessages: Array.isArray(messages[0].messages),
            hasType: !!messages[0].type,
            hasRole: !!messages[0].role,
            hasContent: !!messages[0].content,
            keys: Object.keys(messages[0])
          }
        : null
    })
    ;(messages || []).forEach((item) => {
      if (!item) return

      if (Array.isArray(item.messages)) {
        item.messages.forEach((msg) => {
          if (msg) result.push(msg)
        })
        return
      }

      // Support passing a flat message array directly
      if (item.type || item.role || item.content) {
        result.push(item)
      }
    })

    return result
  }

  /**
   * Generate HTML fragments for conversation messages
   */
  static generateMessagesHTML(messages, agentName) {
    return messages
      .map((msg) => {
        const isUserMessage = ['human', 'user'].includes(msg?.type) || msg?.role === 'user'
        const avatar = isUserMessage ? '👤' : '🤖'
        const senderLabel = isUserMessage ? 'User' : agentName || 'Smart Assistant'
        const messageClass = isUserMessage ? 'user-message' : 'ai-message'
        const timestampRaw = this.getMessageTimestamp(msg)
        const timestamp = this.escapeHtml(this.formatTimestamp(timestampRaw))

        const { content, reasoning } = this.extractMessageContent(msg)
        const contentHTML = content ? this.renderMarkdown(content) : ''
        const reasoningHTML = !isUserMessage ? this.generateReasoningHTML(reasoning) : ''
        const toolCallsHTML = !isUserMessage ? this.generateToolCallsHTML(msg) : ''

        const bodySegments = [
          reasoningHTML,
          contentHTML ? `<div class="markdown-body">${contentHTML}</div>` : '',
          toolCallsHTML
        ].filter(Boolean)

        return `
        <div class="message ${messageClass}">
          <div class="message-header">
            <span class="avatar">${avatar}</span>
            <span class="sender">${this.escapeHtml(senderLabel)}</span>
            <span class="time">${timestamp}</span>
          </div>
          <div class="message-content">
            ${bodySegments.length > 0 ? bodySegments.join('') : '<div class="empty-message">(No content to display for this message yet)</div>'}
          </div>
        </div>
      `
      })
      .join('')
  }

  /**
   * Split message content from reasoning text
   */
  static extractMessageContent(msg = {}) {
    const content = this.normalizeContent(msg?.content)
    let reasoning = msg?.additional_kwargs?.reasoning_content || msg?.reasoning_content || ''
    let visibleContent = content

    if (!reasoning && content.includes('<think')) {
      const thinkRegex = /<think>([\s\S]*?)<\/think>|<think>([\s\S]*)$/i
      const match = content.match(thinkRegex)
      if (match) {
        reasoning = (match[1] || match[2] || '').trim()
        visibleContent = content.replace(match[0], '').trim()
      }
    }

    return {
      content: visibleContent,
      reasoning
    }
  }

  /**
   * Normalize message content
   */
  static normalizeContent(raw) {
    if (raw == null) return ''
    if (typeof raw === 'string') return raw

    if (Array.isArray(raw)) {
      return raw
        .map((item) => {
          if (!item) return ''
          if (typeof item === 'string') return item
          if (typeof item === 'object') {
            return item.text || item.content || item.value || ''
          }
          return String(item)
        })
        .filter(Boolean)
        .join('\n')
        .trim()
    }

    if (typeof raw === 'object') {
      if (typeof raw.text === 'string') return raw.text
      if (typeof raw.content === 'string') return raw.content
      if (Array.isArray(raw.content)) return this.normalizeContent(raw.content)
      try {
        return JSON.stringify(raw, null, 2)
      } catch {
        return String(raw)
      }
    }

    return String(raw)
  }

  /**
   * Generate reasoning HTML
   */
  static generateReasoningHTML(reasoning) {
    if (!reasoning) return ''

    const reasoningHTML = this.renderMarkdown(reasoning)
    if (!reasoningHTML) return ''

    return `
      <details class="reasoning-section">
        <summary class="reasoning-summary">💭 Reasoning process</summary>
        <div class="reasoning-content markdown-body">
          ${reasoningHTML}
        </div>
      </details>
    `
  }

  /**
   * Generate tool call HTML
   */
  static generateToolCallsHTML(msg = {}) {
    const toolCalls = this.normalizeToolCalls(msg)
    if (toolCalls.length === 0) return ''

    const sections = toolCalls
      .map((toolCall) => {
        const toolName = this.escapeHtml(toolCall?.function?.name || toolCall?.name || 'Tool call')
        const argsSource = toolCall?.args ?? toolCall?.function?.arguments
        const args = this.stringifyToolArgs(argsSource)
        const result = this.normalizeToolResult(toolCall?.tool_call_result?.content)
        const isFinished = toolCall?.status === 'success'
        const stateClass = isFinished ? 'done' : 'pending'
        const stateLabel = isFinished ? 'Completed' : 'Running'

        return `
        <details class="tool-call" ${isFinished ? '' : 'open'}>
          <summary>
            <span class="tool-call-title">🔧 ${toolName}</span>
            <span class="tool-call-state ${stateClass}">${stateLabel}</span>
          </summary>
          <div class="tool-call-body">
            ${
              args
                ? `
              <div class="tool-call-args">
                <strong>Arguments</strong>
                <pre>${this.escapeHtml(args)}</pre>
              </div>
            `
                : ''
            }
            ${
              isFinished && result
                ? `
              <div class="tool-call-result">
                <strong>Result</strong>
                <pre>${this.escapeHtml(result)}</pre>
              </div>
            `
                : ''
            }
          </div>
        </details>
      `
      })
      .join('')

    return `<div class="tool-calls">${sections}</div>`
  }

  static normalizeToolCalls(msg = {}) {
    const rawCalls = msg.tool_calls || msg.additional_kwargs?.tool_calls
    if (!rawCalls) return []
    if (Array.isArray(rawCalls)) return rawCalls.filter(Boolean)
    if (typeof rawCalls === 'object') {
      return Object.values(rawCalls).filter(Boolean)
    }
    return []
  }

  static stringifyToolArgs(rawArgs) {
    if (rawArgs == null || rawArgs === '') return ''

    if (typeof rawArgs === 'string') {
      const trimmed = rawArgs.trim()
      if (!trimmed) return ''
      try {
        return JSON.stringify(JSON.parse(trimmed), null, 2)
      } catch {
        return trimmed
      }
    }

    if (typeof rawArgs === 'object') {
      try {
        return JSON.stringify(rawArgs, null, 2)
      } catch {
        return String(rawArgs)
      }
    }

    return String(rawArgs)
  }

  static normalizeToolResult(result) {
    if (!result) return ''
    if (typeof result === 'string') return result.trim()

    if (Array.isArray(result)) {
      return result
        .map((item) => {
          if (!item) return ''
          if (typeof item === 'string') return item
          if (typeof item === 'object') {
            return item.text || item.content || JSON.stringify(item, null, 2)
          }
          return String(item)
        })
        .filter(Boolean)
        .join('\n\n')
        .trim()
    }

    if (typeof result === 'object') {
      if (typeof result.content !== 'undefined') {
        return this.normalizeToolResult(result.content)
      }
      try {
        return JSON.stringify(result, null, 2)
      } catch {
        return String(result)
      }
    }

    return String(result)
  }

  /**
   * Unified Markdown rendering; falls back to simple line breaks on failure
   */
  static renderMarkdown(content) {
    if (!content) return ''
    try {
      return marked.parse(content).trim()
    } catch (error) {
      console.warn('Markdown rendering failed, falling back to plain text:', error)
      return this.escapeHtml(content).replace(/\n/g, '<br>')
    }
  }

  /**
   * Escape HTML
   */
  static escapeHtml(value) {
    if (value == null) return ''
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
  }

  /**
   * Extract message timestamp
   */
  static getMessageTimestamp(msg = {}) {
    const candidates = [
      msg.timestamp,
      msg.created_at,
      msg.createdAt,
      msg.createdTime,
      msg.time,
      msg.datetime,
      msg.date,
      msg.additional_kwargs?.timestamp,
      msg.additional_kwargs?.created_at
    ]

    return candidates.find((value) => value !== undefined && value !== null)
  }

  /**
   * Format timestamp
   */
  static formatTimestamp(raw) {
    const fallback = dayjs().tz('Asia/Shanghai')

    if (raw instanceof Date) {
      return dayjs(raw).tz('Asia/Shanghai').format('YYYY-MM-DD HH:mm:ss')
    }

    if (raw || raw === 0) {
      if (typeof raw === 'number') {
        const value = raw < 1e12 ? raw * 1000 : raw
        return dayjs(value).tz('Asia/Shanghai').format('YYYY-MM-DD HH:mm:ss')
      }

      const parsed = parseToShanghai(raw)
      if (parsed) {
        return parsed.format('YYYY-MM-DD HH:mm:ss')
      }
    }

    return fallback.format('YYYY-MM-DD HH:mm:ss')
  }

  /**
   * Generate the complete HTML document skeleton
   */
  static generateHTMLTemplate(options) {
    const { chatTitle, agentName, agentDescription, exportTime, messagesHTML } = options

    const safeTitle = this.escapeHtml(chatTitle)
    const safeAgentName = this.escapeHtml(agentName)
    const safeDescription = this.escapeHtml(agentDescription).replace(/\n/g, '<br>')
    const safeExportTime = this.escapeHtml(exportTime)

    const descriptionBlock = agentDescription
      ? `<br><strong>Description:</strong> ${safeDescription}`
      : ''

    return chatExportTemplate
      .replace(/{{TITLE}}/g, safeTitle)
      .replace('{{AGENT_NAME}}', safeAgentName)
      .replace('{{DESCRIPTION_BLOCK}}', descriptionBlock)
      .replace('{{EXPORT_TIME}}', safeExportTime)
      .replace('{{MESSAGES}}', messagesHTML)
  }
}

export default ChatExporter
