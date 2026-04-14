<template>
  <div
    v-if="message.message_type === 'multimodal_image' && message.image_content"
    class="message-image"
  >
    <img :src="`data:image/jpeg;base64,${message.image_content}`" alt="Uploaded image" />
  </div>
  <div class="message-box" :class="[message.type, customClasses]">
    <!-- User message -->
    <div
      v-if="message.type === 'human'"
      class="message-copy-btn human-copy"
      @click="copyToClipboard(message.content)"
      :class="{ 'is-copied': isCopied }"
    >
      <Check v-if="isCopied" size="14" />
      <Copy v-else size="14" />
    </div>
    <p v-if="message.type === 'human'" class="message-text">{{ message.content }}</p>

    <p v-else-if="message.type === 'system'" class="message-text-system">{{ message.content }}</p>

    <!-- Assistant message -->
    <div v-else-if="message.type === 'ai'" class="assistant-message">
      <div v-if="parsedData.reasoning_content" class="reasoning-box">
        <a-collapse v-model:activeKey="reasoningActiveKey" :bordered="false">
          <template #expandIcon="{ isActive }">
            <caret-right-outlined :rotate="isActive ? 90 : 0" />
          </template>
          <a-collapse-panel
            key="show"
            :header="message.status == 'reasoning' ? 'Thinking...' : 'Reasoning'"
            class="reasoning-header"
          >
            <p class="reasoning-content">{{ parsedData.reasoning_content }}</p>
          </a-collapse-panel>
        </a-collapse>
      </div>

      <!-- Message content -->
      <MdPreview
        v-if="parsedData.content"
        ref="editorRef"
        editorId="preview-only"
        :theme="theme"
        previewTheme="github"
        :showCodeRowNumber="false"
        :modelValue="parsedData.content"
        :key="message.id"
        class="message-md"
      />

      <div v-else-if="parsedData.reasoning_content" class="empty-block"></div>

      <!-- Error hint block -->
      <div v-if="displayError" class="error-hint">
        <span v-if="getErrorMessage">{{ getErrorMessage }}</span>
        <span v-else-if="message.error_type === 'interrupted'"
          >Response generation was interrupted</span
        >
        <span v-else-if="message.error_type === 'unexpect'"
          >An error occurred during generation</span
        >
        <span v-else-if="message.error_type === 'content_guard_blocked'"
          >Sensitive content detected, output stopped</span
        >
        <span v-else>{{ message.error_type || 'Unknown error' }}</span>
      </div>

      <div v-if="validToolCalls && validToolCalls.length > 0" class="tool-calls-container">
        <div
          v-for="(toolCall, index) in validToolCalls"
          :key="toolCall.id || index"
          class="tool-call-container"
        >
          <ToolCallRenderer :tool-call="toolCall" />
        </div>
      </div>

      <div v-if="message.isStoppedByUser" class="retry-hint">
        You stopped this response generation
        <span class="retry-link" @click="emit('retryStoppedMessage', message.id)"
          >Edit and resend</span
        >
      </div>

      <div
        v-if="
          (message.role == 'received' || message.role == 'assistant') &&
          message.status == 'finished' &&
          showRefs
        "
      >
        <RefsComponent
          :message="message"
          :show-refs="showRefs"
          :is-latest-message="isLatestMessage"
          :sources="messageSources"
          @retry="emit('retry')"
          @openRefs="emit('openRefs', $event)"
        />
      </div>
      <!-- Error message -->
    </div>

    <div v-if="infoStore.debugMode" class="status-info">{{ message }}</div>

    <!-- Custom content -->
    <slot></slot>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CaretRightOutlined } from '@ant-design/icons-vue'
import RefsComponent from '@/components/RefsComponent.vue'
import { Copy, Check } from 'lucide-vue-next'
import { ToolCallRenderer } from '@/components/ToolCallingResult'
import { useAgentStore } from '@/stores/agent'
import { useInfoStore } from '@/stores/info'
import { useThemeStore } from '@/stores/theme'
import { storeToRefs } from 'pinia'
import { MessageProcessor } from '@/utils/messageProcessor'

import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'

const props = defineProps({
  // Message role: 'user'|'assistant'|'sent'|'received'
  message: {
    type: Object,
    required: true
  },
  // Whether processing is in progress
  isProcessing: {
    type: Boolean,
    default: false
  },
  // Custom classes
  customClasses: {
    type: Object,
    default: () => ({})
  },
  // Whether to show reasoning content
  showRefs: {
    type: [Array, Boolean],
    default: () => false
  },
  // Whether this is the latest message
  isLatestMessage: {
    type: Boolean,
    default: false
  },
  // Whether to show debug information (deprecated, use infoStore.debugMode)
  debugMode: {
    type: Boolean,
    default: false
  }
})

const editorRef = ref()

const emit = defineEmits(['retry', 'retryStoppedMessage', 'openRefs'])

// Copy state
const isCopied = ref(false)

const copyToClipboard = async (text) => {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // Fallback for older browsers using execCommand.
      const textArea = document.createElement('textarea')
      textArea.value = text
      textArea.style.position = 'fixed'
      textArea.style.left = '-999999px'
      textArea.style.top = '-999999px'
      document.body.appendChild(textArea)
      textArea.focus()
      textArea.select()
      const successful = document.execCommand('copy')
      document.body.removeChild(textArea)
      if (!successful) throw new Error('execCommand failed')
    }
    isCopied.value = true
    setTimeout(() => {
      isCopied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy: ', err)
  }
}

// Reasoning panel expansion state
const reasoningActiveKey = ref(['hide'])

// Error message handling
const displayError = computed(() => {
  // Simplified error check: only explicit error type markers.
  return !!(props.message.error_type || props.message.extra_metadata?.error_type)
})

const getErrorMessage = computed(() => {
  // Prefer direct error_message first.
  if (props.message.error_message) {
    return props.message.error_message
  }

  // Then try error details in extra_metadata.
  if (props.message.extra_metadata?.error_message) {
    return props.message.extra_metadata.error_message
  }

  // Return default text for known error types.
  switch (props.message.error_type) {
    case 'interrupted':
      return 'Response generation was interrupted'
    case 'content_guard_blocked':
      return 'Sensitive content detected, output stopped'
    case 'unexpect':
      return 'An error occurred during generation'
    case 'agent_error':
      return 'Failed to load agent'
    default:
      return null
  }
})

// Agent store
const agentStore = useAgentStore()
const { availableKnowledgeBases } = storeToRefs(agentStore)
const infoStore = useInfoStore()
const themeStore = useThemeStore()

// Extract message sources
const messageSources = computed(() => {
  if (props.message.type === 'ai') {
    return MessageProcessor.extractSourcesFromMessage(props.message, availableKnowledgeBases.value)
  }
  return { knowledgeChunks: [], webSources: [] }
})

// Theme based on system setting
const theme = computed(() => (themeStore.isDark ? 'dark' : 'light'))

// Filter valid tool calls
const validToolCalls = computed(() => {
  if (!props.message.tool_calls || !Array.isArray(props.message.tool_calls)) {
    return []
  }

  return props.message.tool_calls.filter((toolCall) => {
    // Filter out invalid tool calls
    return (
      toolCall &&
      (toolCall.id || toolCall.name) &&
      (toolCall.args !== undefined ||
        toolCall.function?.arguments !== undefined ||
        toolCall.tool_call_result !== undefined)
    )
  })
})

const parsedData = computed(() => {
  // Start with default values from the prop to avoid mutation.
  let content = props.message.content.trim() || ''
  let reasoning_content = props.message.additional_kwargs?.reasoning_content || ''

  if (reasoning_content) {
    return {
      content,
      reasoning_content
    }
  }

  // Regex to find <think>...</think> or an unclosed <think>... at the end of the string.
  const thinkRegex = /<think>(.*?)<\/think>|<think>(.*?)$/s
  const thinkMatch = content.match(thinkRegex)

  if (thinkMatch) {
    // The captured reasoning is in either group 1 (closed tag) or 2 (unclosed tag).
    reasoning_content = (thinkMatch[1] || thinkMatch[2] || '').trim()
    // Remove the entire matched <think> block from the original content.
    content = content.replace(thinkMatch[0], '').trim()
  }

  return {
    content,
    reasoning_content
  }
})
</script>

<style lang="less" scoped>
.message-box {
  display: inline-block;
  border-radius: 1.5rem;
  margin: 0.8rem 0;
  padding: 0.625rem 1.25rem;
  user-select: text;
  word-break: break-word;
  word-wrap: break-word;
  font-size: 15px;
  line-height: 24px;
  box-sizing: border-box;
  color: var(--gray-10000);
  max-width: 100%;
  position: relative;
  letter-spacing: 0.25px;

  &.human,
  &.sent {
    max-width: 95%;
    color: var(--gray-1000);
    background-color: var(--main-50);
    align-self: flex-end;
    border-radius: 0.5rem;
    padding: 0.5rem 1rem;
  }

  &.assistant,
  &.received,
  &.ai {
    color: initial;
    width: 100%;
    text-align: left;
    margin: 0;
    padding: 0px;
    background-color: transparent;
    border-radius: 0;
  }

  .message-text {
    max-width: 100%;
    margin-bottom: 0;
    white-space: pre-line;
  }

  .message-copy-btn {
    cursor: pointer;
    color: var(--gray-400);
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    flex-shrink: 0;

    &:hover {
      color: var(--main-color);
    }

    &.is-copied {
      color: var(--color-success-500);
      opacity: 1;
    }

    &.human-copy {
      position: absolute;
      left: -28px;
      bottom: 8px;
    }
  }

  &:hover {
    .message-copy-btn {
      opacity: 1;
    }
  }

  .message-text-system {
    max-width: 100%;
    margin-bottom: 0;
    white-space: pre-line;
    color: var(--gray-600);
    font-style: italic;
    font-size: 14px;
    padding: 8px 12px;
    background-color: var(--gray-50);
    border-left: 3px solid var(--gray-300);
    border-radius: 4px;
  }

  .err-msg {
    color: var(--color-error-500);
    border: 1px solid currentColor;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    text-align: left;
    background: var(--color-error-50);
    margin-bottom: 10px;
    cursor: pointer;
  }

  .searching-msg {
    color: var(--gray-700);
    animation: colorPulse 1s infinite ease-in-out;
  }

  .reasoning-box {
    margin-top: 10px;
    margin-bottom: 15px;
    border-radius: 8px;
    border: 1px solid var(--gray-150);
    background-color: var(--gray-25);
    overflow: hidden;
    transition: all 0.2s ease;

    :deep(.ant-collapse) {
      background-color: transparent;
      border: none;

      .ant-collapse-item {
        border: none;

        .ant-collapse-header {
          padding: 8px 12px;
          font-size: 14px;
          font-weight: 500;
          color: var(--gray-700);
          transition: all 0.2s ease;

          .ant-collapse-expand-icon {
            color: var(--gray-400);
          }
        }

        .ant-collapse-content {
          border: none;
          background-color: transparent;

          .ant-collapse-content-box {
            padding: 16px;
            background-color: var(--gray-25);
          }
        }
      }
    }

    .reasoning-content {
      font-size: 13px;
      color: var(--gray-800);
      white-space: pre-wrap;
      margin: 0;
      line-height: 1.6;
    }
  }

  .assistant-message {
    width: 100%;
  }

  .error-hint {
    margin: 10px 0;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    background-color: var(--color-error-50);
    color: var(--color-error-500);
    span {
      line-height: 1.5;
    }
  }

  .status-info {
    display: block;
    background-color: var(--gray-50);
    color: var(--gray-700);
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 10px;
    font-size: 12px;
    font-family: monospace;
    max-height: 200px;
    overflow-y: auto;
  }

  :deep(.tool-calls-container) {
    width: 100%;
    margin-top: 10px;

    .tool-call-container {
      margin-bottom: 10px;

      &:last-child {
        margin-bottom: 0;
      }
    }
  }
}

.retry-hint {
  margin-top: 8px;
  padding: 8px 16px;
  color: var(--gray-600);
  font-size: 14px;
  text-align: left;
}

.retry-link {
  color: var(--color-info-500);
  cursor: pointer;
  margin-left: 4px;

  &:hover {
    text-decoration: underline;
  }
}

.ant-btn-icon-only {
  &:has(.anticon-stop) {
    background-color: var(--color-error-500) !important;

    &:hover {
      background-color: var(--color-error-100) !important;
    }
  }
}

@keyframes colorPulse {
  0% {
    color: var(--gray-700);
  }
  50% {
    color: var(--gray-300);
  }
  100% {
    color: var(--gray-700);
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

// Multimodal message styles
.message-image {
  border-radius: 12px;
  overflow: hidden;
  margin-left: auto;
  /* max-height: 200px; */
  border: 1px solid rgba(255, 255, 255, 0.2);

  img {
    max-width: 100%;
    max-height: 200px;
    object-fit: contain;
  }
}
</style>

<style lang="less" scoped>
:deep(.message-md) {
  margin: 8px 0;
}

:deep(.message-md .md-editor-preview-wrapper) {
  max-width: 100%;
  padding: 0;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Noto Sans SC', 'PingFang SC', 'Noto Sans SC',
    'Microsoft YaHei', 'Hiragino Sans GB', 'Source Han Sans CN', 'Courier New', monospace;

  #preview-only-preview {
    font-size: 1rem;
    line-height: 1.75;
    color: var(--gray-1000);
  }

  h1,
  h2 {
    font-size: 1.2rem;
  }

  h3,
  h4 {
    font-size: 1.1rem;
  }

  h5,
  h6 {
    font-size: 1rem;
  }

  strong {
    font-weight: 500;
  }

  li > p,
  ol > p,
  ul > p {
    margin: 0.25rem 0;
  }

  ul li::marker,
  ol li::marker {
    color: var(--main-bright);
  }

  ul,
  ol {
    padding-left: 1.625rem;
  }

  cite {
    font-size: 12px;
    color: var(--gray-800);
    font-style: normal;
    background-color: var(--gray-200);
    border-radius: 4px;
    outline: 2px solid var(--gray-200);
    padding: 0rem 0.25rem;
    margin-left: 4px;
    cursor: pointer;
    user-select: none;
    position: relative;

    &:hover::after {
      content: attr(source);
      position: absolute;
      bottom: calc(100% + 6px);
      left: 50%;
      transform: translateX(-50%);
      padding: 8px 12px;
      background-color: #222;
      color: #fff;
      font-size: 13px;
      line-height: 1.5;
      border-radius: 6px;
      min-width: 100px;
      max-width: 400px;
      width: max-content;
      white-space: normal;
      word-break: break-word;
      z-index: 1000;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
      pointer-events: none;
      text-align: center;
    }

    &:hover::before {
      content: '';
      position: absolute;
      bottom: 100%;
      left: 50%;
      transform: translateX(-50%);
      border: 5px solid transparent;
      border-top-color: var(--gray-900);
      z-index: 1000;
    }
  }

  a {
    color: var(--main-700);
  }

  .md-editor-code {
    border: var(--gray-50);
    border-radius: 8px;

    .md-editor-code-head {
      background-color: var(--gray-50);
      z-index: 1;

      .md-editor-collapse-tips {
        color: var(--gray-400);
      }
    }
  }

  code {
    font-size: 13px;
    font-family:
      'Menlo', 'Monaco', 'Consolas', 'PingFang SC', 'Noto Sans SC', 'Microsoft YaHei',
      'Hiragino Sans GB', 'Source Han Sans CN', 'Courier New', monospace;
    line-height: 1.5;
    letter-spacing: 0.025em;
    tab-size: 4;
    -moz-tab-size: 4;
    background-color: var(--gray-25);
  }

  p:last-child {
    margin-bottom: 0;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 2em 0;
    font-size: 15px;
    display: table;
    outline: 1px solid var(--gray-100);
    outline-offset: 14px;
    border-radius: 12px;

    thead tr th {
      padding-top: 0;
    }

    thead th,
    tbody th {
      border: none;
      border-bottom: 1px solid var(--gray-200);
    }

    tbody tr:last-child td {
      border-bottom: 1px solid var(--gray-200);
      border: none;
      padding-bottom: 0;
    }
  }

  th,
  td {
    padding: 0.5rem 0rem;
    text-align: left;
    border: none;
  }

  td {
    border-bottom: 1px solid var(--gray-100);
    color: var(--gray-800);
  }

  th {
    font-weight: 600;
    color: var(--gray-800);
  }

  tr {
    background-color: var(--gray-0);
  }

  // tbody tr:last-child td {
  //   border-bottom: none;
  // }
}

:deep(.chat-box.font-smaller #preview-only-preview) {
  font-size: 14px;

  h1,
  h2 {
    font-size: 1.1rem;
  }

  h3,
  h4 {
    font-size: 1rem;
  }
}

:deep(.chat-box.font-larger #preview-only-preview) {
  font-size: 16px;

  h1,
  h2 {
    font-size: 1.3rem;
  }

  h3,
  h4 {
    font-size: 1.2rem;
  }

  h5,
  h6 {
    font-size: 1.1rem;
  }

  code {
    font-size: 14px;
  }
}
</style>
