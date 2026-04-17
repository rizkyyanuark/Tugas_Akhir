<template>
  <a-modal
    v-model:open="visible"
    title="Auto Generate Evaluation Benchmark"
    width="600px"
    :confirmLoading="generating"
    @ok="handleGenerate"
    @cancel="handleCancel"
  >
    <a-form ref="formRef" :model="formState" :rules="rules" layout="vertical">
      <a-form-item label="Benchmark Name" name="name">
        <a-input v-model:value="formState.name" placeholder="Enter benchmark name" />
      </a-form-item>

      <a-form-item label="Description" name="description">
        <a-textarea
          v-model:value="formState.description"
          placeholder="Enter benchmark description (optional)"
          :rows="3"
        />
      </a-form-item>

      <a-form-item label="Generation Parameters" name="params" :extra="extraText">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item
              label="Question Count"
              name="count"
              :labelCol="{ span: 24 }"
              :wrapperCol="{ span: 24 }"
            >
              <a-input-number
                v-model:value="formState.count"
                :min="1"
                :max="100"
                style="width: 100%"
                placeholder="Number of questions to generate"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item
              label="Similar Chunks Count"
              name="neighbors_count"
              :labelCol="{ span: 24 }"
              :wrapperCol="{ span: 24 }"
            >
              <a-input-number
                v-model:value="formState.neighbors_count"
                :min="0"
                :max="10"
                style="width: 100%"
                placeholder="Number of similar chunks selected each time"
              />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form-item>

      <a-form-item label="LLM Configuration" name="llm_config">
        <a-card size="small" title="Configuration Parameters">
          <a-form-item
            label="LLM Model"
            name="llm_model_spec"
            :rules="[{ required: true, message: 'Please select an LLM model' }]"
          >
            <ModelSelectorComponent
              :model_spec="formState.llm_model_spec"
              placeholder="Select an LLM model for question generation"
              size="small"
              @select-model="handleSelectLLMModel"
            />
          </a-form-item>

          <a-form-item
            label="Embedding Model"
            name="embedding_model_id"
            :rules="[{ required: true, message: 'Please select an embedding model' }]"
          >
            <EmbeddingModelSelector
              v-model:value="formState.embedding_model_id"
              placeholder="Select an embedding model for similarity calculation"
              size="default"
            />
          </a-form-item>

          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item
                label="Temperature"
                name="temperature"
                :labelCol="{ span: 24 }"
                :wrapperCol="{ span: 24 }"
              >
                <a-input-number
                  v-model:value="formState.llm_config.temperature"
                  :min="0"
                  :max="2"
                  :step="0.1"
                  style="width: 100%"
                  placeholder="Control generation randomness"
                />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item
                label="Max Tokens"
                name="max_tokens"
                :labelCol="{ span: 24 }"
                :wrapperCol="{ span: 24 }"
              >
                <a-input-number
                  v-model:value="formState.llm_config.max_tokens"
                  :min="100"
                  :max="4000"
                  :step="100"
                  style="width: 100%"
                  placeholder="Maximum generated content length"
                />
              </a-form-item>
            </a-col>
          </a-row>
        </a-card>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, watch, h } from 'vue'
import { message } from 'ant-design-vue'
import { evaluationApi } from '@/apis/knowledge_api'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  databaseId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update:visible', 'success'])

// Reactive state
const formRef = ref()
const generating = ref(false)

const formState = reactive({
  name: '',
  description: '',
  count: 10,
  neighbors_count: 2,
  embedding_model_id: '',
  llm_model_spec: '',
  llm_config: {
    model: '',
    temperature: 0.7,
    max_tokens: 1000
  }
})

// Form validation rules
const rules = {
  name: [
    { required: true, message: 'Please enter a benchmark name', trigger: 'blur' },
    {
      min: 2,
      max: 100,
      message: 'Benchmark name length should be between 2 and 100 characters',
      trigger: 'blur'
    }
  ],
  count: [{ required: true, message: 'Please enter question count', trigger: 'blur' }]
}

// Two-way bind visible
const visible = computed({
  get: () => props.visible,
  set: (val) => emit('update:visible', val)
})

// Help text
const extraText = computed(() =>
  h('span', {}, [
    'Want to learn how benchmark generation works? See ',
    h(
      'a',
      {
        href: 'https://xerrors.github.io/Yuxi/intro/evaluation.html',
        target: '_blank',
        rel: 'noopener noreferrer'
      },
      'Documentation'
    )
  ])
)

// Generate benchmark
const handleGenerate = async () => {
  try {
    // Form validation
    await formRef.value.validate()

    generating.value = true

    const params = {
      name: formState.name,
      description: formState.description,
      count: formState.count,
      neighbors_count: formState.neighbors_count,
      embedding_model_id: formState.embedding_model_id,
      llm_config: {
        ...formState.llm_config,
        model_spec: formState.llm_model_spec
      }
    }

    const response = await evaluationApi.generateBenchmark(props.databaseId, params)

    if (response.message === 'success') {
      message.success('Generation task submitted. Please check results later.')
      handleCancel()
      emit('success')
    } else {
      message.error(response.message || 'Generation failed')
    }
  } catch (error) {
    console.error('Generation failed:', error)
    message.error('Generation failed')
  } finally {
    generating.value = false
  }
}

// Cancel action
const handleCancel = () => {
  visible.value = false
  resetForm()
}

// Reset form
const resetForm = () => {
  formRef.value?.resetFields()
  Object.assign(formState, {
    name: '',
    description: '',
    count: 10,
    neighbors_count: 2,
    embedding_model_id: '',
    llm_model_spec: '',
    llm_config: {
      model: '',
      temperature: 0.7,
      max_tokens: 1000
    }
  })
  generating.value = false
}

// Select LLM model
const handleSelectLLMModel = (modelSpec) => {
  formState.llm_model_spec = modelSpec
  formState.llm_config.model = modelSpec
}

// Watch visible changes
watch(visible, (val) => {
  if (!val) {
    resetForm()
  }
})
</script>

<style lang="less" scoped>
:deep(.ant-card) {
  .ant-card-head {
    min-height: auto;
    padding: 0 12px;
    border-bottom: 1px solid var(--gray-200);

    .ant-card-head-title {
      font-size: 14px;
      padding: 8px 0;
    }
  }
}
</style>
