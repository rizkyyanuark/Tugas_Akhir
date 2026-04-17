<template>
  <!-- Feedback list modal -->
  <a-modal v-model:open="modalVisible" title="User Feedback Details" width="1200px" :footer="null">
    <a-space style="margin-bottom: 16px">
      <a-segmented
        v-model:value="feedbackFilter"
        :options="feedbackOptions"
        @change="loadFeedbacks"
      />
    </a-space>

    <!-- Card list -->
    <div v-if="loadingFeedbacks" class="loading-container">
      <a-spin size="large" />
    </div>

    <div v-else class="feedback-cards-container">
      <div v-for="feedback in feedbacks" :key="feedback.id" class="feedback-card">
        <!-- Card header: user info and feedback type -->
        <div class="card-header">
          <div class="user-info">
            <a-avatar :src="feedback.avatar" :size="32" class="user-avatar">
              {{ feedback.username ? feedback.username.charAt(0).toUpperCase() : 'U' }}
            </a-avatar>
            <div class="user-details">
              <div class="username">{{ feedback.username || 'Unknown user' }}</div>
            </div>
          </div>
          <a-tag
            :color="feedback.rating === 'like' ? 'green' : 'red'"
            class="rating-tag"
            size="small"
          >
            <template #icon>
              <LikeOutlined v-if="feedback.rating === 'like'" />
              <DislikeOutlined v-else />
            </template>
            {{ feedback.rating === 'like' ? 'Like' : 'Dislike' }}
          </a-tag>
        </div>

        <!-- Card content: conversation info, message content, and feedback reason -->
        <div class="card-content">
          <!-- Conversation title -->
          <div class="conversation-section" v-if="feedback.conversation_title">
            <div class="conversation-info">
              <div class="info-item">
                <span
                  class="conversation-title"
                  :class="{ collapsed: !expandedStates.get(`${feedback.id}-conversation`) }"
                >
                  Title: {{ feedback.conversation_title }}
                </span>
                <a-button
                  v-if="shouldShowConversationExpandButton(feedback.conversation_title)"
                  type="link"
                  size="small"
                  @click="toggleConversationExpand(feedback.id)"
                  class="expand-button-inline"
                >
                  {{ expandedStates.get(`${feedback.id}-conversation`) ? 'Collapse' : 'Expand' }}
                </a-button>
              </div>
              <div class="info-item" v-if="!props.agentId">
                <span class="label">Agent:</span>
                <span class="value">{{ feedback.agent_id }}</span>
              </div>
            </div>
          </div>

          <!-- Message content -->
          <div class="message-section">
            <div
              class="message-content"
              :class="{ collapsed: !expandedStates.get(`${feedback.id}-message`) }"
            >
              {{ feedback.message_content }}
            </div>
            <a-button
              v-if="shouldShowExpandButton(feedback.message_content)"
              type="link"
              size="small"
              @click="toggleExpand(feedback.id)"
              class="expand-button"
            >
              {{ expandedStates.get(`${feedback.id}-message`) ? 'Collapse' : 'Expand all' }}
            </a-button>
          </div>

          <!-- Feedback reason -->
          <div v-if="feedback.reason" class="reason-section">
            <div class="reason-content">{{ feedback.reason }}</div>
          </div>
        </div>

        <!-- Card footer: time info -->
        <div class="card-footer">
          <div class="time-info">
            <ClockCircleOutlined />
            <span>{{ formatFullDate(feedback.created_at) }}</span>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="feedbacks.length === 0" class="empty-state">
        <a-empty description="No feedback data yet" />
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { LikeOutlined, DislikeOutlined, ClockCircleOutlined } from '@ant-design/icons-vue'
import { dashboardApi } from '@/apis/dashboard_api'
import { formatFullDateTime } from '@/utils/time'

// Constants
const CONFIG = {
  MESSAGE_MAX_LINES: 8, // Maximum displayed lines for messages
  CONVERSATION_MAX_LINES: 2, // Maximum displayed lines for conversation title
  CONVERSATION_MAX_CHARS: 60, // Character threshold for conversation title
  AVG_CHARS_PER_LINE: 30 // Estimated average chars per line (mixed CJK and English)
}

// Props
const props = defineProps({
  agentId: {
    type: String,
    default: null
  }
})

// Modal state
const modalVisible = ref(false)

// Feedback-related data
const feedbacks = ref([])
const loadingFeedbacks = ref(false)
const feedbackFilter = ref('all')
const feedbackOptions = [
  { label: 'All', value: 'all' },
  { label: 'Like', value: 'like' },
  { label: 'Dislike', value: 'dislike' }
]

// Expand-state mapping (use Map to avoid direct object mutation)
const expandedStates = ref(new Map())

// Show modal
const show = () => {
  modalVisible.value = true
  loadFeedbacks()
}

// Expose method to parent component
defineExpose({ show })

// Helper to estimate number of text lines
const estimateLines = (text) => {
  if (!text) return 0
  return Math.ceil(text.length / CONFIG.AVG_CHARS_PER_LINE)
}

// Determine whether to show expand button
const shouldShowExpandButton = (content) => {
  return estimateLines(content) > CONFIG.MESSAGE_MAX_LINES
}

// Determine whether conversation title needs expand button
const shouldShowConversationExpandButton = (title) => {
  if (!title) return false
  return title.length > CONFIG.CONVERSATION_MAX_CHARS
}

// Toggle expand/collapse state
const toggleExpand = (feedbackId) => {
  const key = `${feedbackId}-message`
  const currentState = expandedStates.value.get(key) ?? false
  expandedStates.value.set(key, !currentState)
}

// Toggle conversation title expand/collapse state
const toggleConversationExpand = (feedbackId) => {
  const key = `${feedbackId}-conversation`
  const currentState = expandedStates.value.get(key) ?? false
  expandedStates.value.set(key, !currentState)
}

// Load feedback list
const loadFeedbacks = async () => {
  loadingFeedbacks.value = true
  try {
    const params = {
      rating: feedbackFilter.value === 'all' ? undefined : feedbackFilter.value,
      agent_id: props.agentId || undefined
    }

    const response = await dashboardApi.getFeedbacks(params)
    feedbacks.value = response
    // Reset expand states
    expandedStates.value.clear()
  } catch (error) {
    console.error('Failed to load feedback list:', error)
    message.error('Failed to load feedback list, please try again later')
    feedbacks.value = []
  } finally {
    loadingFeedbacks.value = false
  }
}

// Format full date
const formatFullDate = (dateString) => formatFullDateTime(dateString)

// Watch agentId changes and reload data
watch(
  () => props.agentId,
  () => {
    if (modalVisible.value) {
      loadFeedbacks()
    }
  }
)
</script>

<style scoped lang="less">
// Loading state
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40px 0;
}

// Card container - adaptive multi-column layout
.feedback-cards-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  max-height: 600px;
  overflow-y: auto;
  padding-right: 8px;

  // Scrollbar styles
  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-track {
    background: var(--gray-100);
    border-radius: 3px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--gray-300);
    border-radius: 3px;

    &:hover {
      background: var(--gray-400);
    }
  }
}

// Feedback card - compact design
.feedback-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-100);
  border-radius: 8px;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;

  &:hover {
    border-color: var(--main-color);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }
}

// Card header - compact
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-100);
  background: var(--gray-25);
  border-radius: 8px 8px 0 0;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  flex-shrink: 0;
}

.user-details {
  .username {
    font-weight: 500;
    color: var(--gray-900);
    font-size: 13px;
    line-height: 1.2;
  }
}

.rating-tag {
  font-weight: 500;
  font-size: 11px;
}

// Card content - compact
.card-content {
  padding: 16px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message-section {
  flex: 1;
}

.message-content {
  background: var(--gray-50);
  padding: 10px;
  border-radius: 6px;
  // border-left: 3px solid var(--main-color);
  font-size: 13px;
  line-height: 1.4;
  color: var(--gray-800);
  word-break: break-word;
  overflow: hidden;
  transition: max-height 0.3s ease;
}

.message-content.collapsed {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 8;
  line-clamp: 8;
  overflow: hidden;
  text-overflow: ellipsis;
}

.expand-button {
  padding: 0;
  height: auto;
  font-size: 12px;
  margin-top: 8px;
  color: var(--main-color);
}

.conversation-section {
  margin: 0;
}

.conversation-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.info-item {
  display: flex;
  align-items: center;
  font-size: 12px;

  .label {
    color: var(--gray-600);
    margin-right: 6px;
    min-width: 50px;
    font-weight: 500;
  }

  .value {
    color: var(--gray-800);
    font-weight: 400;
    word-break: break-all;
  }

  // Conversation title style (shown independently)
  .conversation-title {
    display: block;
    color: var(--gray-700);
    font-size: 13px;
    font-weight: 500;
    line-height: 1.4;
    word-break: break-word;
    transition: all 0.3s ease;

    &.collapsed {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }

  // Use vertical layout when info-item contains conversation title
  &:has(.conversation-title) {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
}

.expand-button-inline {
  padding: 0;
  height: auto;
  font-size: 11px;
  color: var(--main-color);
  align-self: flex-start;
}

.reason-section {
  margin: 0;
}

.reason-content {
  background: var(--color-warning-50);
  padding: 10px;
  border-radius: 6px;
  border-left: 3px solid var(--color-warning-500);
  font-size: 13px;
  line-height: 1.4;
  color: var(--gray-800);
  word-break: break-word;
}

// Card footer - compact
.card-footer {
  padding: 8px 16px;
  border-top: 1px solid var(--gray-100);
  background: var(--gray-25);
  border-radius: 0 0 8px 8px;
}

.time-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--gray-500);
}

// Empty state
.empty-state {
  grid-column: 1 / -1;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
}

// Responsive design
@media (max-width: 768px) {
  .feedback-cards-container {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .card-header {
    padding: 10px 12px;
    gap: 8px;
  }

  .card-content {
    padding: 12px;
    gap: 10px;
  }

  .card-footer {
    padding: 6px 12px;
  }
}

@media (max-width: 480px) {
  .feedback-cards-container {
    gap: 8px;
  }

  .card-header {
    padding: 8px 10px;
  }

  .card-content {
    padding: 10px;
    gap: 8px;
  }

  .message-content,
  .reason-content {
    padding: 8px;
    font-size: 12px;
  }

  .info-item {
    font-size: 11px;
  }
}
</style>
