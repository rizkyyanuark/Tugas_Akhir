<template>
  <div class="ai-textarea-wrapper">
    <a-textarea
      :value="modelValue"
      @update:value="$emit('update:modelValue', $event)"
      :placeholder="placeholder"
      :rows="rows"
      :auto-size="autoSize"
    />
    <a-tooltip v-if="name" title="Use AI to generate or refine the description">
      <a-button
        class="ai-btn"
        type="text"
        size="small"
        :loading="loading"
        @click="generateDescription"
      >
        <template #icon>
          <WandSparkles size="14" />
        </template>
        <span v-if="!loading" class="ai-text">{{ modelValue?.trim() ? 'Refine' : 'Generate' }}</span>
      </a-button>
    </a-tooltip>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { databaseApi } from '@/apis/knowledge_api'
import { WandSparkles } from 'lucide-vue-next'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  name: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: ''
  },
  rows: {
    type: Number,
    default: 4
  },
  autoSize: {
    type: [Boolean, Object],
    default: false
  },
  files: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue'])

const loading = ref(false)

const generateDescription = async () => {
  if (!props.name?.trim()) {
    message.warning('Please enter a knowledge base name first')
    return
  }

  loading.value = true
  try {
    const result = await databaseApi.generateDescription(props.name, props.modelValue, props.files)
    if (result.status === 'success' && result.description) {
      emit('update:modelValue', result.description)
      message.success('Description generated successfully')
    } else {
      message.error(result.message || 'Generation failed')
    }
  } catch (error) {
    console.error('Description generation failed:', error)
    message.error(error.message || 'Description generation failed')
  } finally {
    loading.value = false
  }
}
</script>

<style lang="less" scoped>
.ai-textarea-wrapper {
  position: relative;

  .ai-btn {
    position: absolute;
    opacity: 0.9;
    top: 4px;
    right: 4px;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    height: 24px;
    color: var(--main-color);
    background: var(--gray-50);
    border: 1px solid var(--gray-200);
    border-radius: 4px;
    font-size: 12px;
    transition: all 0.2s ease;

    &:hover {
      background: var(--main-10);
      border-color: var(--main-color);
    }

    .ai-text {
      font-weight: 500;
    }
  }
}
</style>
