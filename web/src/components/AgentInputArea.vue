<template>
  <MessageInputComponent
    ref="inputRef"
    :model-value="modelValue"
    @update:modelValue="updateValue"
    :is-loading="isLoading"
    :disabled="disabled"
    :send-button-disabled="sendButtonDisabled"
    :placeholder="placeholder"
    :mention="mention"
    @send="handleSend"
    @keydown="handleKeyDown"
  >
    <template #top>
      <div v-if="currentImage" class="input-top-stack">
        <ImagePreviewComponent
          :image-data="currentImage"
          @remove="handleImageRemoved"
          class="image-preview-wrapper"
        />
      </div>
    </template>
    <template #options-left>
      <div v-if="isIngestionLocked" class="ingestion-locked-indicator" title="Data Ingestion Locked (Final Engineering Directive)">
        <Lock :size="16" class="lock-icon" />
        <span class="lock-text">Ingestion Locked</span>
      </div>
      <AttachmentOptionsComponent
        v-else-if="supportsFileUpload"
        :disabled="disabled"
        @upload="handleAttachmentUpload"
        @upload-image="handleImageUpload"
        @upload-image-success="handleImageUploadSuccess"
      />
    </template>
    <template #actions-left>
      <div class="input-actions-left">
        <a-popover
          v-if="showTodoEntry"
          v-model:open="todoPopoverOpen"
          placement="topLeft"
          trigger="click"
          overlay-class-name="todo-popover-overlay"
        >
          <template #content>
            <div class="todo-popover-card">
              <div class="todo-popover-header">
                <div class="todo-popover-title-wrap">
                  <span class="todo-popover-title">Current Tasks</span>
                  <span class="todo-popover-summary"
                    >{{ completedTodoCount }}/{{ totalTodoCount }} completed</span
                  >
                </div>
                <span class="todo-popover-progress">{{ todoProgress }}%</span>
              </div>

              <div class="todo-progress-bar">
                <span class="todo-progress-bar-fill" :style="{ width: `${todoProgress}%` }"></span>
              </div>

              <div class="todo-popover-list">
                <div
                  v-for="(todo, index) in todos"
                  :key="`${todo.content}-${index}`"
                  class="todo-item"
                >
                  <div class="todo-item-icon" :class="todo.status || 'unknown'">
                    <CheckCircleOutlined v-if="todo.status === 'completed'" />
                    <SyncOutlined v-else-if="todo.status === 'in_progress'" spin />
                    <ClockCircleOutlined v-else-if="todo.status === 'pending'" />
                    <CloseCircleOutlined v-else-if="todo.status === 'cancelled'" />
                    <QuestionCircleOutlined v-else />
                  </div>
                  <div class="todo-item-body">
                    <span class="todo-item-text">{{ todo.content }}</span>
                    <span class="todo-item-status">{{ getTodoStatusLabel(todo.status) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <button class="input-action-btn" @click.stop>
            <span class="todo-entry-icon" aria-hidden="true">
              <SquareCheck :size="16" />
            </span>
            <span>Todos</span>
          </button>
        </a-popover>
      </div>
    </template>
    <template #actions-right>
      <div class="input-actions-right">
        <button
          v-if="hasActiveThread"
          class="input-action-btn"
          :class="{ active: isPanelOpen }"
          @click.stop="$emit('toggle-panel')"
          title="View Files"
        >
          <FolderCode :size="18" />
          <span>Files</span>
        </button>
        <slot name="actions-left-extra"></slot>
      </div>
    </template>
  </MessageInputComponent>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import MessageInputComponent from '@/components/MessageInputComponent.vue'
import ImagePreviewComponent from '@/components/ImagePreviewComponent.vue'
import AttachmentOptionsComponent from '@/components/AttachmentOptionsComponent.vue'
import { FolderCode, SquareCheck, Lock } from 'lucide-vue-next'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  QuestionCircleOutlined,
  SyncOutlined
} from '@ant-design/icons-vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  sendButtonDisabled: { type: Boolean, default: false },
  mention: { type: Object, default: () => null },
  supportsFileUpload: { type: Boolean, default: false },
  isPanelOpen: { type: Boolean, default: false },
  isIngestionLocked: { type: Boolean, default: false },
  hasActiveThread: { type: Boolean, default: true },
  todos: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits([
  'update:modelValue',
  'send',
  'keydown',
  'upload-attachment',
  'toggle-panel'
])

const inputRef = ref(null)
const currentImage = ref(null)
const todoPopoverOpen = ref(false)
const placeholder = 'Ask anything... use @ to mention resources'

const totalTodoCount = computed(() => props.todos.length)
const completedTodoCount = computed(
  () => props.todos.filter((todo) => todo?.status === 'completed').length
)
const showTodoEntry = computed(() => props.hasActiveThread && totalTodoCount.value > 0)
const todoProgress = computed(() => {
  if (!totalTodoCount.value) return 0
  return Math.round((completedTodoCount.value / totalTodoCount.value) * 100)
})

watch(showTodoEntry, (visible) => {
  if (!visible) {
    todoPopoverOpen.value = false
  }
})

const updateValue = (val) => {
  emit('update:modelValue', val)
}

const handleAttachmentUpload = (files) => {
  if (!files?.length) return
  emit('upload-attachment', files)
}

const handleImageUpload = (imageData) => {
  if (imageData && imageData.success) {
    currentImage.value = imageData
  }
}

const handleImageUploadSuccess = () => {
  if (inputRef.value) {
    inputRef.value.closeOptions()
  }
}

const handleImageRemoved = () => {
  currentImage.value = null
}

const handleSend = () => {
  emit('send', { image: currentImage.value })
  currentImage.value = null
  todoPopoverOpen.value = false
}

const handleKeyDown = (e) => {
  if (props.sendButtonDisabled) {
    return
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else {
    emit('keydown', e)
  }
}

defineExpose({
  focus: () => inputRef.value?.focus(),
  closeOptions: () => inputRef.value?.closeOptions()
})

const getTodoStatusLabel = (status) => {
  const labelMap = {
    completed: 'Completed',
    in_progress: 'In Progress',
    pending: 'Pending',
    cancelled: 'Cancelled'
  }
  return labelMap[status] || 'Unknown Status'
}
</script>

<style lang="less" scoped>
.input-actions-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.input-actions-right {
  display: flex;
  align-items: center;
  margin-right: 8px;
  gap: 2px;
}

.input-top-stack {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

// Shared styles for input action buttons (applied through slot content)
.ingestion-locked-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(255, 77, 79, 0.1);
  border: 1px solid rgba(255, 77, 79, 0.2);
  color: #ff4d4f;
  font-size: 11px;
  font-weight: 500;
  cursor: default;
  user-select: none;
  animation: pulse-red 2s infinite ease-in-out;

  .lock-icon {
    flex-shrink: 0;
  }

  .lock-text {
    white-space: nowrap;
  }
}

@keyframes pulse-red {
  0% { opacity: 0.8; }
  50% { opacity: 1; border-color: rgba(255, 77, 79, 0.4); background: rgba(255, 77, 79, 0.15); }
  100% { opacity: 0.8; }
}

:deep(.input-action-btn) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  // height: 28px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--gray-600);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  background: transparent;
  border: none;

  &:hover {
    color: var(--gray-900);
    background: var(--gray-50);
  }

  &.active {
    color: var(--gray-900);
    background: var(--gray-100);
    font-weight: 500;
  }

  &.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
  }

  span {
    line-height: 1;
  }
}

.todo-entry-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: currentColor;
}

.todo-popover-card {
  width: min(300px, calc(100vw - 32px));
  padding: 14px;
  background: linear-gradient(180deg, var(--gray-50) 0%, var(--gray-50) 100%);
}

.todo-popover-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.todo-popover-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.todo-popover-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
}

.todo-popover-summary {
  font-size: 12px;
  color: var(--gray-500);
}

.todo-popover-progress {
  font-size: 18px;
  line-height: 1;
  font-weight: 700;
  color: var(--gray-800);
}

.todo-progress-bar {
  position: relative;
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: var(--gray-100);
  overflow: hidden;
  margin-bottom: 12px;
}

.todo-progress-bar-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--color-success-500) 0%, var(--color-success-700) 100%);
}

.todo-popover-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
  padding-right: 2px;
}

.todo-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--light-70);
  box-shadow: inset 0 0 0 1px var(--light-70);
}

.todo-item-icon {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--gray-100);
  color: var(--gray-500);

  &.completed {
    background: var(--color-success-10);
    color: var(--color-success-700);
  }

  &.in_progress {
    background: var(--color-info-10);
    color: var(--color-info-700);
  }

  &.pending {
    background: var(--color-warning-10);
    color: var(--color-warning-700);
  }

  &.cancelled {
    background: var(--color-error-10);
    color: var(--color-error-700);
  }
}

.todo-item-body {
  min-width: 0;
}

.todo-item-text {
  font-size: 13px;
  line-height: 1.45;
  color: var(--gray-800);
  word-break: break-word;
  margin-right: 4px;
}

.todo-item-status {
  font-size: 12px;
  color: var(--gray-500);
}

// Responsive hide-text style for slot content
:deep(.hide-text) {
  @media (max-width: 768px) {
    display: none;
  }
}

@media (max-width: 768px) {
  .input-top-stack {
    gap: 8px;
    margin-bottom: 10px;
  }

  .todo-popover-card {
    width: min(320px, calc(100vw - 24px));
    padding: 12px;
  }
}
</style>

<style lang="less">
.todo-popover-overlay {
  .ant-popover-inner {
    padding: 0;
    border-radius: 12px;
    overflow: hidden;
  }
}
</style>
