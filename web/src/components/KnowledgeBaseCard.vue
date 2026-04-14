<template>
  <div class="knowledge-base-card">
    <!-- Title bar -->
    <div class="card-header">
      <div class="header-left">
        <a-button
          @click="backToDatabase"
          class="back-button"
          shape="circle"
          :icon="h(LeftOutlined)"
          type="text"
          size="small"
        ></a-button>
        <h3 class="card-title">{{ database.name || 'Loading database info' }}</h3>
      </div>
      <div class="header-right">
        <a-button type="text" size="small" @click="copyDatabaseId" title="Copy knowledge base ID">
          <template #icon>
            <Copy :size="14" />
          </template>
        </a-button>
        <a-button @click="showEditModal" type="text" size="small">
          <template #icon>
            <Pencil :size="14" />
          </template>
        </a-button>
      </div>
    </div>

    <!-- Card content -->
    <div class="card-content">
      <!-- Description text -->
      <div class="description">
        <p class="description-text">{{ database.description || 'No description available' }}</p>
      </div>

      <!-- Tags -->
      <div class="tags-section">
        <a-tag :color="getKbTypeColor(database.kb_type || 'lightrag')" size="small">
          {{ getKbTypeLabel(database.kb_type || 'lightrag') }}
        </a-tag>
        <a-tag color="blue" size="small">{{ database.embed_info?.name || 'N/A' }}</a-tag>
        <a-tag color="cyan" size="small">{{
          chunkPresetLabelMap[database.additional_params?.chunk_preset_id || 'general'] || 'General'
        }}</a-tag>
      </div>
    </div>
  </div>

  <!-- Edit dialog -->
  <a-modal v-model:open="editModalVisible" title="Edit knowledge base information">
    <template #footer>
      <a-button danger @click="deleteDatabase" style="margin-right: auto; margin-left: 0">
        <template #icon>
          <Trash2 :size="16" style="vertical-align: -3px; margin-right: 4px" />
        </template>
        Delete database
      </a-button>
      <a-button key="back" @click="editModalVisible = false">Cancel</a-button>
      <a-button key="submit" type="primary" @click="handleEditSubmit">Confirm</a-button>
    </template>
    <a-form :model="editForm" :rules="rules" ref="editFormRef" layout="vertical">
      <a-form-item label="Knowledge base name" name="name" required>
        <a-input v-model:value="editForm.name" placeholder="Enter knowledge base name" />
      </a-form-item>
      <a-form-item label="Knowledge base description" name="description">
        <AiTextarea
          v-model="editForm.description"
          :name="editForm.name"
          :files="fileList"
          placeholder="Enter knowledge base description"
          :rows="4"
        />
      </a-form-item>

      <a-form-item
        v-if="database.kb_type !== 'dify'"
        label="Auto-generate questions"
        name="auto_generate_questions"
      >
        <a-switch
          v-model:checked="editForm.auto_generate_questions"
          checked-children="On"
          un-checked-children="Off"
        />
        <span style="margin-left: 8px; font-size: 12px; color: var(--gray-500)"
          >Automatically generate test questions after upload</span
        >
      </a-form-item>

      <a-form-item v-if="database.kb_type !== 'dify'" name="chunk_preset_id">
        <template #label>
          <span class="chunk-preset-label">
            Chunking strategy
            <a-tooltip :title="editPresetDescription">
              <QuestionCircleOutlined class="chunk-preset-help-icon" />
            </a-tooltip>
          </span>
        </template>
        <a-select v-model:value="editForm.chunk_preset_id" :options="chunkPresetOptions" />
      </a-form-item>

      <template v-if="database.kb_type === 'dify'">
        <a-form-item label="Dify API URL" name="dify_api_url">
          <a-input
            v-model:value="editForm.dify_api_url"
            placeholder="e.g.: https://api.dify.ai/v1"
          />
        </a-form-item>
        <a-form-item label="Dify token" name="dify_token">
          <a-input-password
            v-model:value="editForm.dify_token"
            placeholder="Enter Dify API token"
          />
        </a-form-item>
        <a-form-item label="Dataset ID" name="dify_dataset_id">
          <a-input v-model:value="editForm.dify_dataset_id" placeholder="Enter Dify dataset ID" />
        </a-form-item>
      </template>

      <!-- Show LLM config only for LightRAG type -->
      <a-form-item
        v-if="database.kb_type === 'lightrag'"
        label="Language Model (LLM)"
        name="llm_info"
      >
        <ModelSelectorComponent
          :model_spec="llmModelSpec"
          placeholder="Please select a model"
          @select-model="handleLLMSelect"
          style="width: 100%"
        />
      </a-form-item>

      <!-- Share config (super admins can edit all; admins can also edit with backend permission checks) -->
      <a-form-item v-if="canEditShareConfig" label="Share Settings" name="share_config">
        <a-form-item-rest>
          <ShareConfigForm
            ref="shareConfigFormRef"
            :model-value="database.share_config"
            :auto-select-user-dept="true"
          />
        </a-form-item-rest>
      </a-form-item>
      <!-- Show share config in read-only mode when editing is not allowed -->
      <a-form-item
        v-else-if="database.share_config"
        label="Share Settings"
        name="share_config_readonly"
      >
        <div class="share-config-readonly">
          <a-tag :color="database.share_config.is_shared !== false ? 'green' : 'blue'">
            {{
              database.share_config.is_shared !== false
                ? 'Shared with everyone'
                : 'Specific departments'
            }}
          </a-tag>
          <span v-if="database.share_config.is_shared === false" class="dept-names">
            {{ getAccessibleDeptNames() }}
          </span>
        </div>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDatabaseStore } from '@/stores/database'
import { useUserStore } from '@/stores/user'
import { getKbTypeLabel, getKbTypeColor } from '@/utils/kb_utils'
import {
  CHUNK_PRESET_OPTIONS,
  CHUNK_PRESET_LABEL_MAP,
  getChunkPresetDescription
} from '@/utils/chunk_presets'
import { message } from 'ant-design-vue'
import { LeftOutlined, QuestionCircleOutlined } from '@ant-design/icons-vue'
import { Pencil, Trash2, Copy } from 'lucide-vue-next'
import { departmentApi } from '@/apis/department_api'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import AiTextarea from '@/components/AiTextarea.vue'
import ShareConfigForm from '@/components/ShareConfigForm.vue'

const router = useRouter()
const store = useDatabaseStore()
const userStore = useUserStore()

const database = computed(() => store.database)

// Department list (for displaying department names)
const departments = ref([])

// Load department list
const loadDepartments = async () => {
  try {
    const res = await departmentApi.getDepartments()
    departments.value = res.departments || res || []
  } catch (e) {
    console.error('Failed to load department list:', e)
    departments.value = []
  }
}

// Load departments on initialization
onMounted(() => {
  loadDepartments()
})

// Get accessible department names
const getAccessibleDeptNames = () => {
  const deptIds = database.value?.share_config?.accessible_departments || []
  if (deptIds.length === 0) return 'None'
  return deptIds
    .map((id) => {
      const dept = departments.value.find((d) => d.id === id)
      return dept?.name || `Department ${id}`
    })
    .join(', ')
}

// Whether share config is editable
// Rules: 1. Super admins can edit all
//        2. Admins can also edit (backend validates permissions)
const canEditShareConfig = computed(() => {
  if (userStore.isSuperAdmin) {
    return true
  }
  // Admins can edit share config, with backend permission validation
  return userStore.isAdmin
})

const fileList = computed(() => {
  if (!database.value?.files) return []
  return Object.values(database.value.files)
    .map((f) => f.filename)
    .filter(Boolean)
})

// Copy database ID
const copyDatabaseId = async () => {
  if (!database.value.db_id) {
    message.warning('Knowledge base ID is empty')
    return
  }

  try {
    await navigator.clipboard.writeText(database.value.db_id)
    message.success('Knowledge base ID copied to clipboard')
  } catch {
    // Fallback method
    const textArea = document.createElement('textarea')
    textArea.value = database.value.db_id
    document.body.appendChild(textArea)
    textArea.select()
    document.execCommand('copy')
    document.body.removeChild(textArea)
    message.success('Knowledge base ID copied to clipboard')
  }
}

// Return to database list
const backToDatabase = () => {
  router.push('/database')
}

// Edit logic (reused from DatabaseHeader)
const editModalVisible = ref(false)
const editFormRef = ref(null)
const shareConfigFormRef = ref(null)
const editForm = reactive({
  name: '',
  description: '',
  auto_generate_questions: false,
  chunk_preset_id: 'general',
  llm_info: {
    provider: '',
    model_name: ''
  },
  dify_api_url: '',
  dify_token: '',
  dify_dataset_id: ''
})

const chunkPresetOptions = CHUNK_PRESET_OPTIONS.map(({ label, value }) => ({ label, value }))
const chunkPresetLabelMap = CHUNK_PRESET_LABEL_MAP
const editPresetDescription = computed(() => getChunkPresetDescription(editForm.chunk_preset_id))

const rules = {
  name: [{ required: true, message: 'Please enter a knowledge base name' }]
}

// Open edit modal
const showEditModal = () => {
  console.log('[showEditModal] invoked')

  editForm.name = database.value.name || ''
  editForm.description = database.value.description || ''
  editForm.auto_generate_questions =
    database.value.additional_params?.auto_generate_questions || false
  editForm.chunk_preset_id = database.value.additional_params?.chunk_preset_id || 'general'
  editForm.dify_api_url = database.value.additional_params?.dify_api_url || ''
  editForm.dify_token = database.value.additional_params?.dify_token || ''
  editForm.dify_dataset_id = database.value.additional_params?.dify_dataset_id || ''

  // If type is LightRAG, load current LLM config
  if (database.value.kb_type === 'lightrag') {
    const llmInfo = database.value.llm_info || {}
    editForm.llm_info.provider = llmInfo.provider || ''
    editForm.llm_info.model_name = llmInfo.model_name || ''
  }

  editModalVisible.value = true
}

const handleEditSubmit = () => {
  editFormRef.value
    .validate()
    .then(async () => {
      // Validate share config
      if (shareConfigFormRef.value) {
        const validation = shareConfigFormRef.value.validate()
        if (!validation.valid) {
          message.warning(validation.message)
          return
        }
      }

      // Get current values directly from ShareConfigForm
      let finalIsShared = true
      let finalDeptIds = []

      if (shareConfigFormRef.value) {
        const formConfig = shareConfigFormRef.value.config
        finalIsShared = formConfig.is_shared
        finalDeptIds = formConfig.accessible_department_ids || []
      }

      console.log(
        '[handleEditSubmit] fetched directly from component - is_shared:',
        finalIsShared,
        'dept_ids:',
        JSON.stringify(finalDeptIds)
      )

      const updateData = {
        name: editForm.name,
        description: editForm.description,
        additional_params: {},
        share_config: {
          is_shared: finalIsShared,
          accessible_departments: finalIsShared ? [] : finalDeptIds
        }
      }

      if (database.value.kb_type === 'dify') {
        if (
          !editForm.dify_api_url?.trim() ||
          !editForm.dify_token?.trim() ||
          !editForm.dify_dataset_id?.trim()
        ) {
          message.error('Please complete Dify API URL, Token, and Dataset ID')
          return
        }
        if (!editForm.dify_api_url.trim().endsWith('/v1')) {
          message.error('Dify API URL must end with /v1')
          return
        }
        updateData.additional_params = {
          dify_api_url: editForm.dify_api_url.trim(),
          dify_token: editForm.dify_token.trim(),
          dify_dataset_id: editForm.dify_dataset_id.trim()
        }
      } else {
        updateData.additional_params = {
          auto_generate_questions: editForm.auto_generate_questions,
          chunk_preset_id: editForm.chunk_preset_id || 'general'
        }
      }

      console.log(
        '[handleEditSubmit] updateData.share_config:',
        JSON.stringify(updateData.share_config)
      )

      // If type is LightRAG, include llm_info
      if (database.value.kb_type === 'lightrag') {
        updateData.llm_info = {
          provider: editForm.llm_info.provider,
          model_name: editForm.llm_info.model_name
        }
      }

      await store.updateDatabaseInfo(updateData)
      editModalVisible.value = false
    })
    .catch((err) => {
      console.error('Form validation failed:', err)
    })
}

// Handle LLM model selection
const llmModelSpec = computed(() => {
  const provider = editForm.llm_info?.provider || ''
  const modelName = editForm.llm_info?.model_name || ''
  if (provider && modelName) {
    return `${provider}/${modelName}`
  }
  return ''
})

const handleLLMSelect = (spec) => {
  console.log('LLM selected:', spec)
  if (typeof spec !== 'string' || !spec) return

  const index = spec.indexOf('/')
  const provider = index !== -1 ? spec.slice(0, index) : ''
  const modelName = index !== -1 ? spec.slice(index + 1) : ''

  editForm.llm_info.provider = provider
  editForm.llm_info.model_name = modelName
}

const deleteDatabase = () => {
  store.deleteDatabase()
}
</script>

<style lang="less" scoped>
.knowledge-base-card {
  background: linear-gradient(120deg, var(--main-30) 0%, var(--gray-0) 100%);
  border-radius: 12px;
  border: 1px solid var(--gray-200);
  margin-bottom: 8px;
}

// Read-only share config display
.share-config-readonly {
  display: flex;
  align-items: center;
  gap: 8px;

  .dept-names {
    font-size: 13px;
    color: var(--gray-600);
  }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;

  .header-left {
    display: flex;
    align-items: center;
    gap: 4px;
    flex: 1;
    min-width: 0;

    button.back-button {
      margin-left: -5px;
      font-size: 10px;
    }
  }

  .card-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--gray-800);
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    // flex: 1;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;

    button {
      color: var(--gray-500);
      height: 100%;
    }

    button:hover {
      color: var(--gray-700);
      background-color: var(--gray-100);
    }
  }
}

.card-content {
  padding: 0 16px 16px 16px;
}

.description {
  margin-bottom: 12px;

  .description-text {
    font-size: 14px;
    color: var(--gray-700);
    line-height: 1.5;
    margin: 0;
  }
}

.tags-section {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.chunk-preset-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chunk-preset-help-icon {
  color: var(--gray-500);
  cursor: help;
  font-size: 14px;
}
</style>
