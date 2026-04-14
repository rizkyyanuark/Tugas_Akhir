<template>
  <a-modal
    v-model:open="visible"
    title="Upload Evaluation Benchmark"
    width="600px"
    :confirmLoading="uploading"
    @ok="handleUpload"
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

      <a-form-item label="Benchmark File" name="file" :extra="extraText">
        <a-upload-dragger
          v-model:fileList="fileList"
          name="file"
          :multiple="false"
          accept=".jsonl"
          :before-upload="beforeUpload"
          @remove="handleRemove"
        >
          <p class="ant-upload-text">
            <FileTextOutlined />
            Click or drag a file to this area to upload
          </p>
          <p class="ant-upload-hint">Only JSONL files are supported (.jsonl)</p>
        </a-upload-dragger>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, watch, h } from 'vue'
import { message } from 'ant-design-vue'
import { FileTextOutlined } from '@ant-design/icons-vue'
import { evaluationApi } from '@/apis/knowledge_api'

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
const fileList = ref([])
const uploading = ref(false)

const formState = reactive({
  name: '',
  description: '',
  file: null
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
  file: [{ required: true, message: 'Please select a benchmark file', trigger: 'change' }]
}

// Two-way bind visible
const visible = computed({
  get: () => props.visible,
  set: (val) => emit('update:visible', val)
})

// Help text
const extraText = computed(() =>
  h('span', {}, [
    'Need benchmark format details? See ',
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

// Pre-upload file validation
const beforeUpload = async (file) => {
  // Check file type
  if (!file.name.endsWith('.jsonl')) {
    message.error('Only JSONL files are supported')
    return false
  }

  // Check file size (100MB limit)
  const isLt100M = file.size / 1024 / 1024 < 100
  if (!isLt100M) {
    message.error('File size must not exceed 100MB')
    return false
  }

  try {
    // Read file content and validate format
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = (e) => resolve(e.target.result)
      reader.onerror = () => reject(new Error('Failed to read file'))
      reader.readAsText(file)
    })

    const lines = content.trim().split('\n')

    // Ensure at least one line exists
    if (lines.length === 0) {
      message.error('File cannot be empty')
      return false
    }

    // Validate JSON format
    for (let i = 0; i < Math.min(5, lines.length); i++) {
      const line = lines[i].trim()
      if (line) {
        JSON.parse(line)
      }
    }

    // Validation passed, set file
    formState.file = file
    return true
  } catch (error) {
    if (error instanceof SyntaxError) {
      message.error('Invalid file format, please check JSONL format')
    } else {
      message.error('File validation failed: ' + error.message)
    }
    return false
  }
}

// Remove file
const handleRemove = () => {
  formState.file = null
}

// Upload file
const handleUpload = async () => {
  try {
    // Form validation
    await formRef.value.validate()

    if (!formState.file) {
      message.error('Please select a benchmark file')
      return
    }

    uploading.value = true

    const response = await evaluationApi.uploadBenchmark(props.databaseId, formState.file, {
      name: formState.name,
      description: formState.description
    })

    if (response.message === 'success') {
      message.success('Upload successful')
      handleCancel()
      emit('success')
    } else {
      message.error(response.message || 'Upload failed')
    }
  } catch (error) {
    console.error('Upload failed:', error)
    message.error('Upload failed')
  } finally {
    uploading.value = false
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
  fileList.value = []
  formState.file = null
  uploading.value = false
}

// Watch visible changes
watch(visible, (val) => {
  if (!val) {
    resetForm()
  }
})
</script>

<style lang="less" scoped>
:deep(.ant-upload-dragger) {
  .ant-upload-text {
    font-size: 16px;
    color: var(--gray-700);

    .anticon {
      font-size: 48px;
      color: var(--gray-400);
      margin-bottom: 16px;
    }
  }

  .ant-upload-hint {
    color: var(--gray-500);
  }
}
</style>
