<template>
  <div class="database-container layout-container">
    <ViewSwitchHeader
      title="Knowledge Base"
      :active-key="knowledgeActiveView"
      :items="knowledgeViewItems"
      :loading="dbState.listLoading"
      aria-label="Knowledge Base View Switch"
    >
      <template #actions>
        <a-button type="primary" @click="state.openNewDatabaseModel = true">
          New Knowledge Base
        </a-button>
      </template>
    </ViewSwitchHeader>

    <a-modal
      :open="state.openNewDatabaseModel"
      title="Create Knowledge Base"
      :confirm-loading="dbState.creating"
      @ok="handleCreateDatabase"
      @cancel="cancelCreateDatabase"
      class="new-database-modal"
      width="800px"
      destroyOnClose
    >
      <!-- Knowledge Base Type Selection -->
      <h3>Knowledge Base Type<span style="color: var(--color-error-500)">*</span></h3>
      <div class="kb-type-cards">
        <div
          v-for="(typeInfo, typeKey) in orderedKbTypes"
          :key="typeKey"
          class="kb-type-card"
          :class="{ active: newDatabase.kb_type === typeKey }"
          :data-type="typeKey"
          @click="handleKbTypeChange(typeKey)"
        >
          <div class="card-header">
            <component :is="getKbTypeIcon(typeKey)" class="type-icon" />
            <span class="type-title">{{ getKbTypeLabel(typeKey) }}</span>
          </div>
          <div class="card-description">{{ typeInfo.description }}</div>
        </div>
      </div>

      <!-- Type description -->
      <!-- <div class="kb-type-guide" v-if="newDatabase.kb_type">
        <a-alert
          :message="getKbTypeDescription(newDatabase.kb_type)"
          :type="getKbTypeAlertType(newDatabase.kb_type)"
          show-icon
          style="margin: 12px 0;"
        />
      </div> -->

      <h3>Knowledge Base Name<span style="color: var(--color-error-500)">*</span></h3>
      <a-input
        v-model:value="newDatabase.name"
        placeholder="Enter knowledge base name"
        size="large"
      />

      <template v-if="newDatabase.kb_type !== 'dify'">
        <h3>Embedding Model</h3>
        <EmbeddingModelSelector
          v-model:value="newDatabase.embed_model_name"
          style="width: 100%"
          size="large"
          placeholder="Please select an embedding model"
        />
      </template>

      <div v-if="newDatabase.kb_type !== 'dify'" class="chunk-preset-title-row">
        <h3 style="margin: 0">Chunking Strategy</h3>
        <a-tooltip :title="selectedPresetDescription">
          <QuestionCircleOutlined class="chunk-preset-help-icon" />
        </a-tooltip>
      </div>
      <a-select
        v-if="newDatabase.kb_type !== 'dify'"
        v-model:value="newDatabase.chunk_preset_id"
        :options="chunkPresetOptions"
        style="width: 100%"
        size="large"
      />

      <!-- Language selection and LLM selection for LightRAG only -->
      <div v-if="newDatabase.kb_type === 'lightrag'">
        <h3 style="margin-top: 20px">Language</h3>
        <a-select
          v-model:value="newDatabase.language"
          :options="languageOptions"
          style="width: 100%"
          size="large"
          :dropdown-match-select-width="false"
        />

        <h3 style="margin-top: 20px">Large Language Model (LLM)</h3>
        <p style="color: var(--gray-700); font-size: 14px">Configure language models in settings</p>
        <ModelSelectorComponent
          :model_spec="llmModelSpec"
          placeholder="Please select a model"
          @select-model="handleLLMSelect"
          size="large"
          style="width: 100%; height: 60px"
        />
      </div>

      <div v-if="newDatabase.kb_type === 'dify'">
        <h3 style="margin-top: 20px">Dify API URL</h3>
        <a-input
          v-model:value="newDatabase.dify_api_url"
          placeholder="e.g.: https://api.dify.ai/v1"
          size="large"
        />

        <h3 style="margin-top: 20px">Dify Token</h3>
        <a-input-password
          v-model:value="newDatabase.dify_token"
          placeholder="Please enter Dify API Token"
          size="large"
        />

        <h3 style="margin-top: 20px">Dataset ID</h3>
        <a-input
          v-model:value="newDatabase.dify_dataset_id"
          placeholder="Please enter Dify dataset_id"
          size="large"
        />
      </div>

      <h3 style="margin-top: 20px">Description</h3>
      <p style="color: var(--gray-700); font-size: 14px">
        In the agent workflow, this description serves as the tool description. The agent selects
        appropriate tools based on the knowledge base title and description. A more detailed
        description helps the agent make better choices.
      </p>
      <AiTextarea
        v-model="newDatabase.description"
        :name="newDatabase.name"
        placeholder="New knowledge base description"
        :auto-size="{ minRows: 3, maxRows: 10 }"
      />

      <!-- Privacy settings (temporarily hidden)
      <h3 style="margin-top: 20px">Privacy Settings</h3>
      <div class="privacy-config">
        <a-switch
          v-model:checked="newDatabase.is_private"
          checked-children="Private"
          un-checked-children="Public"
          size="default"
        />
        <span style="margin-left: 12px">Set as private knowledge base</span>
        <a-tooltip
          title="This attribute is currently unused. In some agent designs, specific models and strategies can be decided based on this flag. For example, choose stricter data processing and access control for private bases to protect sensitive information."
        >
          <InfoCircleOutlined style="margin-left: 8px; color: var(--gray-500); cursor: help" />
        </a-tooltip>
      </div>
      -->

      <!-- Sharing Configuration -->
      <h3>Sharing Settings</h3>
      <ShareConfigForm v-model="shareConfig" :auto-select-user-dept="true" />
      <template #footer>
        <a-button key="back" @click="cancelCreateDatabase">Cancel</a-button>
        <a-button
          key="submit"
          type="primary"
          :loading="dbState.creating"
          @click="handleCreateDatabase"
          >Create</a-button
        >
      </template>
    </a-modal>

    <!-- Loading State -->
    <div v-if="dbState.listLoading" class="loading-container">
      <a-spin size="large" />
      <p>Loading knowledge base...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!databases || databases.length === 0" class="empty-state">
      <h3 class="empty-title">No Knowledge Base Found</h3>
      <p class="empty-description">
        Create your first knowledge base to start managing documents and knowledge.
      </p>
      <a-button type="primary" size="large" @click="state.openNewDatabaseModel = true">
        <template #icon>
          <PlusOutlined />
        </template>
        Create Knowledge Base
      </a-button>
    </div>

    <!-- Database List -->
    <div v-else class="databases">
      <div
        v-for="database in databases"
        :key="database.db_id"
        class="database dbcard"
        @click="navigateToDatabase(database.db_id)"
      >
        <!-- Private KB Lock Icon -->
        <LockOutlined
          v-if="database.metadata?.is_private"
          class="private-lock-icon"
          title="Private Knowledge Base"
        />
        <div class="top">
          <div class="icon">
            <component :is="getKbTypeIcon(database.kb_type || 'lightrag')" />
          </div>
          <div class="info">
            <h3>{{ database.name }}</h3>
            <p>
              <span>{{ database.row_count || 0 }} Files</span>
              <span class="created-time-inline" v-if="database.created_at">
                {{ formatCreatedTime(database.created_at) }}
              </span>
            </p>
          </div>
        </div>
        <!-- <a-tooltip :title="database.description || 'No description provided'">
          <p class="description">{{ database.description || 'No description provided' }}</p>
        </a-tooltip> -->
        <p class="description">{{ database.description || 'No description provided' }}</p>
        <div class="tags">
          <a-tag
            :bordered="false"
            :color="getKbTypeColor(database.kb_type || 'lightrag')"
            class="kb-type-tag"
            size="small"
          >
            {{ getKbTypeLabel(database.kb_type || 'lightrag') }}
          </a-tag>
          <!-- Keep only the last segment split by / -->
          <a-tag color="blue" v-if="database.embed_info?.name" :bordered="false">{{
            database.embed_info.name.split('/').slice(-1)[0]
          }}</a-tag>
        </div>
        <!-- <button @click="deleteDatabase(database.collection_name)">Delete</button> -->
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useConfigStore } from '@/stores/config'
import { useDatabaseStore } from '@/stores/database'
import { LockOutlined, PlusOutlined, QuestionCircleOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { typeApi } from '@/apis/knowledge_api'
import ViewSwitchHeader from '@/components/ViewSwitchHeader.vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'
import ShareConfigForm from '@/components/ShareConfigForm.vue'
import dayjs, { parseToShanghai } from '@/utils/time'
import AiTextarea from '@/components/AiTextarea.vue'
import { getKbTypeLabel, getKbTypeIcon, getKbTypeColor } from '@/utils/kb_utils'
import { CHUNK_PRESET_OPTIONS, getChunkPresetDescription } from '@/utils/chunk_presets'

const route = useRoute()
const router = useRouter()
const configStore = useConfigStore()
const databaseStore = useDatabaseStore()

// Store state refs
const { databases, state: dbState } = storeToRefs(databaseStore)

const knowledgeActiveView = 'documents'
const knowledgeViewItems = [
  { key: 'documents', label: 'Document Library', path: '/database' },
  { key: 'graph', label: 'Knowledge Graph', path: '/graph' }
]

const state = reactive({
  openNewDatabaseModel: false
})

// Share config state (used for request payload)
const shareConfig = ref({
  is_shared: true,
  accessible_department_ids: []
})

// Language options (English values for backend/LightRAG compatibility)
const languageOptions = [
  { label: 'Chinese', value: 'Chinese' },
  { label: 'English', value: 'English' },
  { label: 'Japanese', value: 'Japanese' },
  { label: 'Korean', value: 'Korean' },
  { label: 'German', value: 'German' },
  { label: 'French', value: 'French' },
  { label: 'Spanish', value: 'Spanish' },
  { label: 'Portuguese', value: 'Portuguese' },
  { label: 'Russian', value: 'Russian' },
  { label: 'Arabic', value: 'Arabic' },
  { label: 'Hindi', value: 'Hindi' }
]

const chunkPresetOptions = CHUNK_PRESET_OPTIONS.map(({ label, value }) => ({ label, value }))

const createEmptyDatabaseForm = () => ({
  name: '',
  description: '',
  embed_model_name: configStore.config?.embed_model,
  kb_type: 'milvus',
  is_private: false,
  storage: '',
  chunk_preset_id: 'general',
  language: 'Chinese',
  llm_info: {
    provider: '',
    model_name: ''
  },
  dify_api_url: '',
  dify_token: '',
  dify_dataset_id: ''
})

const newDatabase = reactive(createEmptyDatabaseForm())

const selectedPresetDescription = computed(() =>
  getChunkPresetDescription(newDatabase.chunk_preset_id)
)

const llmModelSpec = computed(() => {
  const provider = newDatabase.llm_info?.provider || ''
  const modelName = newDatabase.llm_info?.model_name || ''
  if (provider && modelName) {
    return `${provider}/${modelName}`
  }
  return ''
})

// Supported knowledge base types
const supportedKbTypes = ref({})

// Ordered knowledge base types
const orderedKbTypes = computed(() => supportedKbTypes.value)

// Load supported knowledge base types
const loadSupportedKbTypes = async () => {
  try {
    const data = await typeApi.getKnowledgeBaseTypes()
    supportedKbTypes.value = data.kb_types
    console.log('Supported KB Types:', supportedKbTypes.value)
  } catch (error) {
    console.error('Failed to load KB types:', error)
    // Set default type on failure
    supportedKbTypes.value = {
      lightrag: {
        description:
          'Knowledge base based on graph retrieval, supporting entity relationship building and complex queries',
        class_name: 'LightRagKB'
      }
    }
  }
}

// Re-ranker model info is now read directly from configStore.config.reranker_names

const resetNewDatabase = () => {
  Object.assign(newDatabase, createEmptyDatabaseForm())
  // Reset share config
  shareConfig.value = {
    is_shared: true,
    accessible_department_ids: []
  }
}

const cancelCreateDatabase = () => {
  state.openNewDatabaseModel = false
  resetNewDatabase()
}

// Format creation time
const formatCreatedTime = (createdAt) => {
  if (!createdAt) return ''
  const parsed = parseToShanghai(createdAt)
  if (!parsed) return ''

  const today = dayjs().startOf('day')
  const createdDay = parsed.startOf('day')
  const diffInDays = today.diff(createdDay, 'day')

  if (diffInDays === 0) {
    return 'Created Today'
  }
  if (diffInDays === 1) {
    return 'Created Yesterday'
  }
  if (diffInDays < 7) {
    return `Created ${diffInDays} days ago`
  }
  if (diffInDays < 30) {
    const weeks = Math.floor(diffInDays / 7)
    return `Created ${weeks} weeks ago`
  }
  if (diffInDays < 365) {
    const months = Math.floor(diffInDays / 30)
    return `Created ${months} months ago`
  }
  const years = Math.floor(diffInDays / 365)
  return `Created ${years} years ago`
}

// Handle knowledge base type changes
const handleKbTypeChange = (type) => {
  console.log('Knowledge base type changed:', type)
  resetNewDatabase()
  newDatabase.kb_type = type
}

// Handle LLM selection
const handleLLMSelect = (spec) => {
  console.log('LLM selected:', spec)
  if (typeof spec !== 'string' || !spec) return

  const index = spec.indexOf('/')
  const provider = index !== -1 ? spec.slice(0, index) : ''
  const modelName = index !== -1 ? spec.slice(index + 1) : ''

  newDatabase.llm_info.provider = provider
  newDatabase.llm_info.model_name = modelName
}

// Build request payload (form-data mapping only)
const buildRequestData = () => {
  const requestData = {
    database_name: newDatabase.name.trim(),
    description: newDatabase.description?.trim() || '',
    kb_type: newDatabase.kb_type,
    additional_params: {}
  }

  if (newDatabase.kb_type !== 'dify') {
    requestData.embed_model_name = newDatabase.embed_model_name || configStore.config.embed_model
    requestData.additional_params.is_private = newDatabase.is_private || false
    requestData.additional_params.chunk_preset_id = newDatabase.chunk_preset_id || 'general'
  }

  // Add share config
  requestData.share_config = {
    is_shared: shareConfig.value.is_shared,
    accessible_departments: shareConfig.value.is_shared
      ? []
      : shareConfig.value.accessible_department_ids || []
  }

  // Add type-specific configuration
  if (['milvus'].includes(newDatabase.kb_type)) {
    if (newDatabase.storage) {
      requestData.additional_params.storage = newDatabase.storage
    }
  }

  if (newDatabase.kb_type === 'lightrag') {
    requestData.additional_params.language = newDatabase.language || 'English'
    if (newDatabase.llm_info.provider && newDatabase.llm_info.model_name) {
      requestData.llm_info = {
        provider: newDatabase.llm_info.provider,
        model_name: newDatabase.llm_info.model_name
      }
    }
  }

  if (newDatabase.kb_type === 'dify') {
    requestData.additional_params.dify_api_url = (newDatabase.dify_api_url || '').trim()
    requestData.additional_params.dify_token = (newDatabase.dify_token || '').trim()
    requestData.additional_params.dify_dataset_id = (newDatabase.dify_dataset_id || '').trim()
  }

  return requestData
}

// Handle create action
const handleCreateDatabase = async () => {
  if (newDatabase.kb_type === 'dify') {
    if (
      !newDatabase.dify_api_url?.trim() ||
      !newDatabase.dify_token?.trim() ||
      !newDatabase.dify_dataset_id?.trim()
    ) {
      message.error('Please fill in Dify API URL, Token, and Dataset ID fully')
      return
    }
    if (!newDatabase.dify_api_url.trim().endsWith('/v1')) {
      message.error('Dify API URL must end with /v1')
      return
    }
  }

  const requestData = buildRequestData()
  try {
    await databaseStore.createDatabase(requestData)
    resetNewDatabase()
    state.openNewDatabaseModel = false
  } catch {
    // Error is already handled in store
  }
}

const navigateToDatabase = (databaseId) => {
  router.push({ path: `/database/${databaseId}` })
}

watch(
  () => route.path,
  (newPath) => {
    if (newPath === '/database') {
      databaseStore.loadDatabases()
    }
  }
)

onMounted(() => {
  loadSupportedKbTypes()
  databaseStore.loadDatabases()
})
</script>

<style lang="less" scoped>
.new-database-modal {
  .chunk-preset-title-row {
    margin-top: 20px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .chunk-preset-help-icon {
    color: var(--gray-500);
    cursor: help;
    font-size: 14px;
  }

  .kb-type-guide {
    margin: 12px 0;
  }

  .privacy-config {
    display: flex;
    align-items: center;
    margin-bottom: 12px;
  }

  .kb-type-cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin: 16px 0;

    @media (max-width: 768px) {
      grid-template-columns: 1fr;
      gap: 12px;
    }

    .kb-type-card {
      border: 2px solid var(--gray-150);
      border-radius: 12px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.3s ease;
      background: var(--gray-0);
      position: relative;
      overflow: hidden;

      &:hover {
        border-color: var(--main-color);
      }

      &.active {
        border-color: var(--main-color);
        background: var(--main-10);
        .type-icon {
          color: var(--main-color);
        }
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 12px;

        .type-icon {
          width: 24px;
          height: 24px;
          color: var(--main-color);
          flex-shrink: 0;
        }

        .type-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--gray-800);
        }
      }

      .card-description {
        font-size: 13px;
        color: var(--gray-600);
        line-height: 1.5;
        margin-bottom: 0;
        // min-height: 40px;
      }

      .deprecated-badge {
        background: var(--color-error-100);
        color: var(--color-error-600);
        font-size: 10px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
        margin-left: auto;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        cursor: help;
        transition: all 0.2s ease;

        &:hover {
          background: var(--color-error-200);
          color: var(--color-error-700);
        }
      }
    }
  }

  .chunk-config {
    margin-top: 16px;
    padding: 12px 16px;
    background-color: var(--gray-25);
    border-radius: 6px;
    border: 1px solid var(--gray-150);

    h3 {
      margin-top: 0;
      margin-bottom: 12px;
      color: var(--gray-800);
    }

    .chunk-params {
      display: flex;
      flex-direction: column;
      gap: 12px;

      .param-row {
        display: flex;
        align-items: center;
        gap: 12px;

        label {
          min-width: 80px;
          font-weight: 500;
          color: var(--gray-700);
        }

        .param-hint {
          font-size: 12px;
          color: var(--gray-500);
          margin-left: 8px;
        }
      }
    }
  }
}

.database-container {
  .databases {
    .database {
      .top {
        .info {
          h3 {
            display: block;
          }
        }
      }
    }
  }
}
.database-actions,
.document-actions {
  margin-bottom: 20px;
}
.databases {
  padding: 12px 16px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.database,
.graphbase {
  background: linear-gradient(45deg, var(--gray-0) 0%, var(--gray-25) 100%);
  box-shadow: 0px 1px 2px 0px var(--shadow-2);
  border: 1px solid var(--gray-50);
  transition: all 0.3s;
  position: relative;

  &:hover {
    background: linear-gradient(45deg, var(--gray-0) 0%, var(--main-30) 100%);
    box-shadow: 0px 1px 5px var(--shadow-3);
  }
}

.dbcard,
.database {
  width: 100%;
  padding: 8px 12px;
  border-radius: 8px;
  height: 140px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  position: relative; // Positioning context for the absolute lock icon
  overflow: hidden;

  .private-lock-icon {
    position: absolute;
    top: 20px;
    right: 20px;
    color: var(--gray-600);
    background: linear-gradient(135deg, var(--gray-0) 0%, var(--gray-100) 100%);
    font-size: 12px;
    border-radius: 8px;
    padding: 6px;
    z-index: 2;
    box-shadow: 0px 2px 4px var(--shadow-2);
    border: 1px solid var(--gray-100);
  }

  .top {
    display: flex;
    align-items: center;
    height: 54px;
    margin-bottom: 14px;

    .icon {
      width: 50px;
      height: 50px;
      font-size: 24px;
      margin-right: 14px;
      display: flex;
      justify-content: center;
      align-items: center;
      background: var(--main-30);
      border-radius: 12px;
      border: 1px solid var(--gray-150);
      color: var(--main-color);
      position: relative;
    }

    .info {
      flex: 1;
      min-width: 0;

      h3,
      p {
        margin: 0;
        color: var(--gray-10000);
      }

      h3 {
        font-size: 16px;
        font-weight: 600;
        letter-spacing: -0.02em;
        line-height: 1.4;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      p {
        color: var(--gray-700);
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 4px;
        font-weight: 400;

        .created-time-inline {
          color: var(--gray-700);
          font-size: 11px;
          font-weight: 400;
          background: var(--gray-50);
          padding: 2px 6px;
          border-radius: 4px;
        }
      }
    }
  }

  .description {
    color: var(--gray-600);
    overflow: hidden;
    display: -webkit-box;
    line-clamp: 1;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
    text-overflow: ellipsis;
    margin-bottom: 12px;
    font-size: 13px;
    font-weight: 400;
    flex: 1;
  }

  .tags {
    opacity: 0.8;
  }
}

.database-empty {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  flex-direction: column;
  color: var(--gray-900);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  text-align: center;

  .empty-title {
    font-size: 20px;
    font-weight: 600;
    color: var(--gray-900);
    margin: 0 0 12px 0;
    letter-spacing: -0.02em;
  }

  .empty-description {
    font-size: 14px;
    color: var(--gray-600);
    margin: 0 0 32px 0;
    line-height: 1.5;
    max-width: 320px;
  }

  .ant-btn {
    height: 44px;
    padding: 0 24px;
    font-size: 15px;
    font-weight: 500;
  }
}

.database-container {
  padding: 0;
}

.loading-container {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  height: 300px;
  gap: 16px;
}

.new-database-modal {
  h3 {
    margin-top: 10px;
  }
}
</style>
