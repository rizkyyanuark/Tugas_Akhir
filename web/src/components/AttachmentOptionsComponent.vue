<template>
  <div class="attachment-options">
    <div class="option-item">
      <label class="attachment-upload-label" :class="{ disabled: disabled }">
        <input
          ref="fileInputRef"
          type="file"
          multiple
          :disabled="disabled"
          @change="handleFileChange"
          style="display: none"
        />
        <a-tooltip title="Supports any file format <= 5 MB" placement="right">
          <div class="option-content">
            <FileText :size="14" class="option-icon" />
            <span class="option-text">Add Attachment</span>
          </div>
        </a-tooltip>
      </label>
    </div>

    <div class="option-item" @click="handleImageUpload">
      <a-tooltip title="Supports jpg/jpeg/png/gif <= 5 MB" placement="right">
        <div class="option-content">
          <Image :size="14" class="option-icon" />
          <span class="option-text">Upload Image</span>
        </div>
      </a-tooltip>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { FileText, Image } from 'lucide-vue-next'
import { message } from 'ant-design-vue'
import { multimodalApi } from '@/apis/agent_api'

const fileInputRef = ref(null)

const props = defineProps({
  disabled: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['upload', 'upload-image', 'upload-image-success'])

// Handle file input change.
const handleFileChange = (event) => {
  const files = event.target.files
  if (files && files.length > 0) {
    emit('upload', Array.from(files))
  }
  // Reset input so the same file can be selected again.
  event.target.value = ''
}

// Handle image upload.
const handleImageUpload = () => {
  if (props.disabled) return

  // Create a hidden file input.
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.multiple = false
  input.style.display = 'none'

  input.onchange = async (event) => {
    const file = event.target.files[0]
    if (file) {
      await processImageUpload(file)
    }
    document.body.removeChild(input)
  }

  document.body.appendChild(input)
  input.click()

  emit('upload-image')
}

// Process image upload.
const processImageUpload = async (file) => {
  try {
    // Validate file size (10MB).
    if (file.size > 10 * 1024 * 1024) {
      message.error('Image file is too large. Please choose an image smaller than 10MB.')
      return
    }

    // Validate file type.
    if (!file.type.startsWith('image/')) {
      message.error('Please select a valid image file.')
      return
    }

    message.loading({ content: 'Processing image...', key: 'image-upload' })

    const result = await multimodalApi.uploadImage(file)

    if (result.success) {
      message.success({
        content: 'Image processed successfully.',
        key: 'image-upload',
        duration: 2
      })

      // Emit success event with processed image payload.
      emit('upload-image', {
        success: true,
        imageContent: result.image_content,
        thumbnailContent: result.thumbnail_content,
        width: result.width,
        height: result.height,
        format: result.format,
        mimeType: result.mime_type || file.type,
        sizeBytes: result.size_bytes,
        originalName: file.name
      })

      // Notify parent to close attachment options.
      emit('upload-image-success')
    } else {
      message.error({
        content: `Image processing failed: ${result.error}`,
        key: 'image-upload'
      })
    }
  } catch (error) {
    console.error('Image upload failed:', error)
    message.error({
      content: `Image upload failed: ${error.message || 'Unknown error'}`,
      key: 'image-upload'
    })
  }
}
</script>

<style lang="less" scoped>
.attachment-options {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 120px;
}

.option-item {
  cursor: pointer;
  transition: all 0.2s ease;

  &.disabled {
    cursor: not-allowed;
    opacity: 0.5;

    .option-content {
      color: var(--gray-400);
    }
  }
}

.option-content {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  color: var(--gray-700);
  font-size: 12px;
  border-radius: 6px;
  transition: all 0.15s ease;

  .option-item:hover & {
    color: var(--main-color);
    background-color: var(--gray-50);
  }
}

.option-icon {
  flex-shrink: 0;
  color: inherit;
}

.option-text {
  font-weight: 500;
}

.attachment-upload-label {
  display: block;
  width: 100%;
  cursor: pointer;

  &.disabled {
    cursor: not-allowed;
    opacity: 0.5;

    .option-content {
      color: var(--gray-400);
    }
  }
}
</style>
