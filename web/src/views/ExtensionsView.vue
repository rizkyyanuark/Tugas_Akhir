<template>
  <div class="extensions-view extension-page-root">
    <ViewSwitchHeader
      v-model:active-key="activeTab"
      title="Extension Management"
      :items="extensionTabs"
      aria-label="Extension management tabs"
    >
      <template #actions>
        <div class="extension-header-actions">
          <template v-if="activeTab === 'skills'">
            <a-button
              class="lucide-icon-btn"
              :disabled="skillsLoading || skillsImporting"
              @click="handleOpenRemoteInstall"
            >
              <Computer :size="14" />
              <span>Remote Install</span>
            </a-button>
            <a-upload
              accept=".zip,.md"
              :show-upload-list="false"
              :custom-request="handleImportUpload"
              :before-upload="beforeSkillUpload"
              :disabled="skillsLoading || skillsImporting"
            >
              <a-button type="primary" class="lucide-icon-btn" :loading="skillsImporting">
                <Upload :size="14" />
                <span>Upload Skill</span>
              </a-button>
            </a-upload>
          </template>

          <template v-else-if="activeTab === 'mcp'">
            <a-button type="primary" class="lucide-icon-btn" @click="handleMcpAdd">
              <Plus :size="14" />
              <span>Add MCP</span>
            </a-button>
          </template>

          <template v-else-if="activeTab === 'subagents'">
            <a-button type="primary" class="lucide-icon-btn" @click="handleSubagentAdd">
              <Plus :size="14" />
              <span>Add</span>
            </a-button>
          </template>
        </div>
      </template>
    </ViewSwitchHeader>

    <div class="extensions-content">
      <div v-show="activeTab === 'tools'" class="tab-panel">
        <ToolsManagerComponent />
      </div>
      <div v-show="activeTab === 'skills'" class="tab-panel">
        <SkillsManagerComponent ref="skillsRef" @import="handleSkillsImport" />
      </div>
      <div v-show="activeTab === 'mcp'" class="tab-panel">
        <McpServersComponent ref="mcpRef" @add="handleMcpAdd" />
      </div>
      <div v-show="activeTab === 'subagents'" class="tab-panel">
        <SubAgentsComponent ref="subagentsRef" @add="handleSubagentAdd" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { Upload, Plus, Computer } from 'lucide-vue-next'
import SkillsManagerComponent from '@/components/SkillsManagerComponent.vue'
import ToolsManagerComponent from '@/components/ToolsManagerComponent.vue'
import McpServersComponent from '@/components/McpServersComponent.vue'
import SubAgentsComponent from '@/components/SubAgentsComponent.vue'
import ViewSwitchHeader from '@/components/ViewSwitchHeader.vue'

const route = useRoute()
const activeTab = ref('tools')
const skillsRef = ref(null)
const mcpRef = ref(null)
const subagentsRef = ref(null)

const extensionTabs = [
  { key: 'tools', label: 'Tools' },
  { key: 'mcp', label: 'MCP' },
  { key: 'subagents', label: 'Subagents' },
  { key: 'skills', label: 'Skills' }
]

watch(
  () => route.query,
  (query) => {
    if (query.tab && ['tools', 'skills', 'mcp', 'subagents'].includes(query.tab)) {
      activeTab.value = query.tab
    }
  },
  { immediate: true }
)

const skillsLoading = ref(false)
const skillsImporting = ref(false)

const updateSkillsState = (loading, importing) => {
  skillsLoading.value = loading
  skillsImporting.value = importing
}

const handleSkillsImport = () => {
  handleSkillsRefresh()
}

const handleSkillsRefresh = () => {
  if (skillsRef.value?.fetchSkills) {
    updateSkillsState(true, skillsImporting.value)
    skillsRef.value.fetchSkills().finally(() => {
      updateSkillsState(false, skillsImporting.value)
    })
  }
}

const handleOpenRemoteInstall = () => {
  if (skillsRef.value?.openRemoteInstallModal) {
    skillsRef.value.openRemoteInstallModal()
  }
}

const handleMcpAdd = () => {
  if (mcpRef.value?.showAddModal) {
    mcpRef.value.showAddModal()
  }
}

const handleSubagentAdd = () => {
  if (subagentsRef.value?.showAddModal) {
    subagentsRef.value.showAddModal()
  }
}

const beforeSkillUpload = (file) => {
  const lowerName = file.name.toLowerCase()
  if (!lowerName.endsWith('.zip') && lowerName !== 'skill.md') {
    message.error('Only .zip files or SKILL.md are supported')
    return false
  }
  return true
}

const handleImportUpload = async ({ file, onSuccess, onError }) => {
  if (skillsRef.value?.handleImportUpload) {
    updateSkillsState(skillsLoading.value, true)
    try {
      await skillsRef.value.handleImportUpload({ file, onSuccess, onError })
      handleSkillsImport()
    } catch (error) {
      onError?.(error)
    } finally {
      updateSkillsState(skillsLoading.value, false)
    }
  }
}
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';

.extensions-view {
  .extension-header-actions {
    display: flex;
    gap: 8px;
  }

  .extensions-content {
    flex: 1;
    min-height: 0;
    overflow: hidden;

    .tab-panel {
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }
  }
}
</style>
