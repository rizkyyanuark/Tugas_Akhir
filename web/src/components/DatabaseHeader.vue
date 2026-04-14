<template>
  <HeaderComponent
    :title="database.name || 'Loading database information'"
    :loading="loading"
    class="database-info-header"
  >
    <template #left>
      <a-button
        @click="backToDatabase"
        shape="circle"
        :icon="h(LeftOutlined)"
        type="text"
      ></a-button>
    </template>
    <template #behind-title>
      <a-button type="link" @click="showEditModal" :style="{ padding: '0px', color: 'inherit' }">
        <EditOutlined />
      </a-button>
    </template>
    <template #actions>
      <div class="header-info">
        <span class="db-id"
          >ID:
          <span style="user-select: all">{{ database.db_id || 'N/A' }}</span>
        </span>
        <span class="file-count">{{ database.row_count || 0 }} files</span>
        <a-tag color="blue">{{ database.embed_info?.name }}</a-tag>
        <a-tag
          :color="getKbTypeColor(database.kb_type || 'lightrag')"
          class="kb-type-tag"
          size="small"
        >
          <component :is="getKbTypeIcon(database.kb_type || 'lightrag')" class="type-icon" />
          {{ getKbTypeLabel(database.kb_type || 'lightrag') }}
        </a-tag>
      </div>
    </template>
  </HeaderComponent>

  <!-- Edit dialog -->
  <a-modal v-model:open="editModalVisible" title="Edit knowledge base information">
    <template #footer>
      <a-button danger @click="deleteDatabase" style="margin-right: auto; margin-left: 0">
        <DeleteOutlined /> Delete database
      </a-button>
      <a-button key="back" @click="editModalVisible = false">Cancel</a-button>
      <a-button key="submit" type="primary" @click="handleEditSubmit">Confirm</a-button>
    </template>
    <a-form :model="editForm" :rules="rules" ref="editFormRef" layout="vertical">
      <a-form-item label="Knowledge base name" name="name" required>
        <a-input v-model:value="editForm.name" placeholder="Please enter a knowledge base name" />
      </a-form-item>
      <a-form-item label="Knowledge base description" name="description">
        <AiTextarea
          v-model="editForm.description"
          :name="editForm.name"
          placeholder="Please enter a knowledge base description"
          :rows="4"
        />
      </a-form-item>
      <!-- Show LLM settings only for LightRAG type -->
      <a-form-item
        v-if="database.kb_type === 'lightrag'"
        label="Language model (LLM)"
        name="llm_info"
      >
        <ModelSelectorComponent
          :model_spec="llmModelSpec"
          placeholder="Select model"
          @select-model="handleLLMSelect"
          style="width: 100%"
        />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useDatabaseStore } from '@/stores/database'
import { getKbTypeLabel, getKbTypeIcon, getKbTypeColor } from '@/utils/kb_utils'
import { LeftOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import HeaderComponent from '@/components/HeaderComponent.vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import AiTextarea from '@/components/AiTextarea.vue'
import { h } from 'vue'

const router = useRouter()
const store = useDatabaseStore()

const database = computed(() => store.database)
const loading = computed(() => store.state.databaseLoading)

const editModalVisible = ref(false)
const editFormRef = ref(null)
const editForm = reactive({
  name: '',
  description: '',
  llm_info: {
    provider: '',
    model_name: ''
  }
})

const rules = {
  name: [{ required: true, message: 'Please enter a knowledge base name' }]
}

const backToDatabase = () => {
  router.push('/database')
}

const showEditModal = () => {
  editForm.name = database.value.name || ''
  editForm.description = database.value.description || ''
  // Load current LLM settings for LightRAG type
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
      const updateData = {
        name: editForm.name,
        description: editForm.description
      }

      // Include llm_info for LightRAG type
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

// LLM model selection handler
const llmModelSpec = computed(() => {
  const provider = editForm.llm_info?.provider || ''
  const modelName = editForm.llm_info?.model_name || ''
  if (provider && modelName) {
    return `${provider}/${modelName}`
  }
  return ''
})

const handleLLMSelect = (spec) => {
  console.log('LLM selection:', spec)
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

<style scoped>
.database-info-header {
  padding: 8px;
  height: 50px;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.db-id {
  font-size: 12px;
  color: var(--gray-500);
}

.file-count {
  font-size: 12px;
  color: var(--gray-500);
}

.kb-type-tag {
  display: flex;
  align-items: center;
  gap: 4px;
}

.type-icon {
  width: 14px;
  height: 14px;
}
</style>
