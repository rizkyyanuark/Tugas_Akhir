<template>
  <div class="skills-manager-container extension-page-root">
    <div v-if="loading" class="loading-bar-wrapper">
      <div class="loading-bar"></div>
    </div>
    <div class="layout-wrapper" :class="{ 'content-loading': loading }">
      <!-- 左侧：技能列表 -->
      <div class="sidebar-list">
        <div class="sidebar-toolbar">
          <div class="search-box">
            <a-input
              v-model:value="searchQuery"
              placeholder="Search skills..."
              allow-clear
              class="search-input"
            >
              <template #prefix><Search :size="14" class="text-muted" /></template>
            </a-input>
          </div>

          <a-tooltip title="Refresh Skills">
            <a-button class="sidebar-tool" :disabled="loading" @click="fetchSkills">
              <RotateCw :size="14" />
            </a-button>
          </a-tooltip>
        </div>

        <div class="list-container">
          <div
            v-if="
              filteredInstalledSkills.length === 0 && filteredUninstalledBuiltinSkills.length === 0
            "
            class="empty-text"
          >
            <a-empty :image="false" description="No matching skills" />
          </div>
          <div v-if="filteredInstalledSkills.length" class="list-section-title">Installed Skills</div>
          <template
            v-for="(skill, index) in filteredInstalledSkills"
            :key="`installed-${skill.slug}`"
          >
            <div
              class="list-item extension-list-item"
              :class="{ active: currentSkill?.slug === skill.slug }"
              @click="selectSkill(skill)"
            >
              <div class="item-main-row">
                <div class="item-header">
                  <BookMarked :size="16" class="item-icon" />
                  <span class="item-name">{{ skill.name }}</span>
                </div>
                <div class="item-status">
                  <span class="status-chip status-chip-success">Installed</span>
                  <button
                    type="button"
                    class="inline-hover-action"
                    @click.stop="confirmDeleteSkill(skill)"
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div class="item-details">
                <span class="item-desc">{{ skill.description || 'No description' }}</span>
                <div class="item-tags">
                  <span class="source-tag" :class="{ builtin: skill.sourceType === 'builtin' }">{{
                    skill.sourceLabel
                  }}</span>
                </div>
              </div>
            </div>
            <div
              v-if="
                index < filteredInstalledSkills.length - 1 ||
                filteredUninstalledBuiltinSkills.length > 0
              "
              class="list-separator"
            ></div>
          </template>

          <div v-if="filteredUninstalledBuiltinSkills.length" class="list-section-title">
            Available Skills
          </div>
          <template
            v-for="(skill, index) in filteredUninstalledBuiltinSkills"
            :key="`builtin-${skill.slug}`"
          >
            <div
              class="list-item extension-list-item"
              :class="{ active: currentSkill?.slug === skill.slug }"
              @click="selectSkill(skill)"
            >
              <div class="item-main-row">
                <div class="item-header">
                  <BookMarked :size="16" class="item-icon" />
                  <span class="item-name">{{ skill.name }}</span>
                </div>
                <div class="item-status">
                  <button
                    type="button"
                    class="skill-inline-action skill-inline-action-primary"
                    @click.stop="handleInstallBuiltin(skill)"
                  >
                    Install
                  </button>
                </div>
              </div>
              <div class="item-details">
                <span class="item-desc">{{ skill.description || 'No description' }}</span>
                <div class="item-tags">
                  <span class="source-tag builtin">Built-in</span>
                </div>
              </div>
            </div>
            <div
              v-if="index < filteredUninstalledBuiltinSkills.length - 1"
              class="list-separator"
            ></div>
          </template>
        </div>
      </div>

      <!-- 右侧：详情面板 -->
      <div class="main-panel">
        <div v-if="!currentSkill" class="unselected-state">
          <div class="hint-box">
            <FileCode :size="40" class="text-muted" />
            <p>Please select a skill package from the left to edit</p>
          </div>
        </div>

        <template v-else>
          <div class="panel-top-bar">
            <div class="panel-title-stack">
              <h2>{{ currentSkill.name }}</h2>
              <!-- <code>{{ currentSkill.slug }}</code> -->
            </div>
            <div class="panel-actions">
              <a-space :size="8">
                <span
                  v-if="currentSkillStatusLabel"
                  class="panel-status-chip"
                  :class="{ warning: currentSkillStatusTone === 'warning' }"
                >
                  {{ currentSkillStatusLabel }}
                </span>
                <button
                  v-if="currentSkill.is_builtin_spec && currentSkill.status === 'not_installed'"
                  type="button"
                  @click="handleInstallBuiltin(currentSkill)"
                  class="lucide-icon-btn extension-panel-action extension-panel-action-primary"
                >
                  <span>Install</span>
                </button>
                <button
                  v-if="currentSkill.is_builtin_spec && currentSkill.status === 'update_available'"
                  type="button"
                  @click="handleUpdateBuiltin(currentSkill)"
                  class="lucide-icon-btn extension-panel-action extension-panel-action-secondary"
                >
                  <span>Update</span>
                </button>
                <button
                  v-if="isInstalledSkill"
                  type="button"
                  @click="handleExport"
                  class="lucide-icon-btn extension-panel-action extension-panel-action-secondary"
                >
                  <Download :size="14" />
                  <span>Export</span>
                </button>
                <button
                  v-if="isInstalledSkill"
                  type="button"
                  @click="confirmDeleteSkill"
                  class="lucide-icon-btn extension-panel-action extension-panel-action-danger"
                >
                  <Trash2 :size="14" />
                  <span>{{ isBuiltinInstalledSkill ? 'Uninstall' : 'Delete' }}</span>
                </button>
              </a-space>
            </div>
          </div>

          <div v-if="!isInstalledSkill" class="builtin-uninstalled-state">
            <h3>{{ currentSkill.description }}</h3>
            <p>Version {{ currentSkill.version }}</p>
            <a-button type="primary" @click="handleInstallBuiltin(currentSkill)"
              >Install Built-in Skill</a-button
            >
          </div>

          <a-tabs v-else v-model:activeKey="activeTab" class="minimal-tabs">
            <a-tab-pane key="editor">
              <template #tab>
                <span class="tab-title"><FileText :size="14" />Code</span>
              </template>
              <div class="workspace">
                <div class="tree-container">
                  <div class="tree-header">
                    <span class="label">Project Structure</span>
                    <div class="tree-actions">
                      <a-tooltip v-if="!isBuiltinInstalledSkill" title="New File"
                        ><button @click="openCreateModal(false)"><FilePlus :size="14" /></button
                      ></a-tooltip>
                      <a-tooltip v-if="!isBuiltinInstalledSkill" title="New Directory"
                        ><button @click="openCreateModal(true)"><FolderPlus :size="14" /></button
                      ></a-tooltip>
                      <a-tooltip title="Refresh"
                        ><button @click="reloadTree"><RotateCw :size="14" /></button
                      ></a-tooltip>
                    </div>
                  </div>
                  <div class="tree-content">
                    <FileTreeComponent
                      v-model:selectedKeys="selectedTreeKeys"
                      v-model:expandedKeys="expandedKeys"
                      :tree-data="treeData"
                      @select="handleTreeSelect"
                    />
                  </div>
                </div>

                <div class="editor-container">
                  <div class="editor-header">
                    <div class="current-path">
                      <File :size="14" />
                      <span>{{ selectedPath || 'No file selected' }}</span>
                      <span v-if="canSave" class="save-hint">●</span>
                    </div>
                    <div class="header-actions">
                      <a-button
                        v-if="isMarkdownFile && selectedPath"
                        size="small"
                        @click="viewMode = viewMode === 'edit' ? 'preview' : 'edit'"
                        class="lucide-icon-btn view-toggle-btn"
                        :title="viewMode === 'edit' ? 'Preview' : 'Edit'"
                      >
                        <Eye v-if="viewMode === 'edit'" :size="14" />
                        <Edit3 v-else :size="14" />
                        <span>{{ viewMode === 'edit' ? 'Preview' : 'Edit' }}</span>
                      </a-button>
                      <a-button
                        v-if="!isBuiltinInstalledSkill"
                        type="primary"
                        size="small"
                        @click="saveCurrentFile"
                        :disabled="!canSave"
                        :loading="savingFile"
                        class="lucide-icon-btn"
                      >
                        <Save :size="14" />
                        <span>Save</span>
                      </a-button>
                    </div>
                  </div>
                  <div class="editor-main">
                    <a-empty
                      v-if="!selectedPath || selectedIsDir"
                      description="Select a file to start editing"
                      class="mt-40"
                    />
                    <template v-else>
                      <MdPreview
                        v-if="viewMode === 'preview'"
                        :modelValue="fileContent"
                        :theme="theme"
                        previewTheme="github"
                        class="markdown-preview flat-md-preview"
                      />
                      <a-textarea
                        v-else
                        v-model:value="fileContent"
                        class="pure-editor"
                        :readonly="isBuiltinInstalledSkill"
                        spellcheck="false"
                      />
                    </template>
                  </div>
                </div>
              </div>
            </a-tab-pane>

            <a-tab-pane key="dependencies">
              <template #tab>
                <span class="tab-title"><Layers :size="14" />Dependencies</span>
              </template>
              <div class="config-view">
                <div class="config-header">
                  <div class="text">
                    <h3>Dependencies</h3>
                    <p>Configure the tools, MCPs, and other skills required by this skill.</p>
                  </div>
                  <a-button
                    type="primary"
                    :loading="savingDependencies"
                    @click="saveDependencies"
                    class="lucide-icon-btn"
                  >
                    <Save :size="14" />
                    <span>Update Dependencies</span>
                  </a-button>
                </div>

                <div class="config-form">
                  <a-form layout="vertical">
                    <a-form-item label="Tool Dependencies (Tools)">
                      <a-select
                        v-model:value="dependencyForm.tool_dependencies"
                        mode="multiple"
                        :options="toolDependencyOptions"
                        placeholder="Select tools..."
                        allow-clear
                        show-search
                      />
                    </a-form-item>
                    <a-form-item label="MCP Dependencies">
                      <a-select
                        v-model:value="dependencyForm.mcp_dependencies"
                        mode="multiple"
                        :options="mcpDependencyOptions"
                        placeholder="Select MCP service..."
                        allow-clear
                        show-search
                      />
                    </a-form-item>
                    <a-form-item label="Skill Dependencies">
                      <a-select
                        v-model:value="dependencyForm.skill_dependencies"
                        mode="multiple"
                        :options="skillDependencyOptions"
                        placeholder="Select skills..."
                        allow-clear
                        show-search
                      />
                    </a-form-item>
                  </a-form>
                </div>
              </div>
            </a-tab-pane>
          </a-tabs>
        </template>
      </div>
    </div>

    <!-- 弹窗 -->
    <a-modal
      v-model:open="createModalVisible"
      :title="createForm.isDir ? 'New Directory' : 'New File'"
      @ok="handleCreateNode"
      :confirm-loading="creatingNode"
      width="400px"
    >
      <a-form layout="vertical" class="pt-12">
        <a-form-item label="Path (Relative to root)" required>
          <a-input v-model:value="createForm.path" placeholder="src/main.py" />
        </a-form-item>
        <a-form-item v-if="!createForm.isDir" label="Content">
          <a-textarea v-model:value="createForm.content" :rows="5" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="remoteInstallModalVisible"
      title="Install Remote Skill"
      :footer="null"
      width="560px"
      :closable="!installingRemoteSkill"
      :mask-closable="!installingRemoteSkill"
      :keyboard="!installingRemoteSkill"
    >
      <div class="remote-install-panel modal-mode">
        <div class="panel-header-text">
          <span class="title">Pull and import to current system via skills.sh</span>
          <span class="desc">
            Supports `owner/repo` or full GitHub URL. Visit
            <a href="https://skills.sh/" target="_blank" rel="noopener noreferrer">skills.sh</a>
            to find available skills
          </span>
        </div>
        <a-form layout="vertical" class="remote-install-form">
          <a-form-item label="Source Repository">
            <a-input
              v-model:value="remoteInstallForm.source"
              placeholder="anthropics/skills or GitHub URL"
              :disabled="installingRemoteSkill"
            />
          </a-form-item>
          <a-form-item label="Skill Name">
            <a-select
              v-model:value="remoteInstallForm.skills"
              mode="tags"
              :options="filteredRemoteSkillOptions"
              placeholder="frontend-design"
              allow-clear
              show-search
              :disabled="installingRemoteSkill"
              :filter-option="filterRemoteSkillOption"
              :max-tag-count="6"
            />
          </a-form-item>
          <div class="remote-install-actions">
            <a-button
              :loading="listingRemoteSkills"
              :disabled="installingRemoteSkill"
              @click="handleListRemoteSkills"
            >
              View Installable Skills
            </a-button>
            <a-button
              type="primary"
              :loading="installingRemoteSkill"
              :disabled="listingRemoteSkills"
              @click="handleInstallRemoteSkill"
            >
              Install
            </a-button>
            <span v-if="remoteInstallStatusText" class="remote-install-status">
              {{ remoteInstallStatusText }}
            </span>
          </div>
          <div v-if="remoteSkillOptions.length" class="remote-skill-summary">
            Found {{ remoteSkillOptions.length }} skills, you can filter by typing.
          </div>
        </a-form>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'
import { useThemeStore } from '@/stores/theme'
import {
  RotateCw,
  Download,
  Trash2,
  Save,
  FileText,
  Layers,
  FilePlus,
  FolderPlus,
  File,
  Search,
  BookMarked,
  FileCode,
  Eye,
  Edit3
} from 'lucide-vue-next'
import { skillApi } from '@/apis/skill_api'
import FileTreeComponent from '@/components/FileTreeComponent.vue'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const themeStore = useThemeStore()
const theme = computed(() => (themeStore.isDark ? 'dark' : 'light'))

const loading = ref(false)
const importing = ref(false)
const listingRemoteSkills = ref(false)
const installingRemoteSkill = ref(false)
const savingFile = ref(false)
const creatingNode = ref(false)
const savingDependencies = ref(false)
const activeTab = ref('editor')
const searchQuery = ref('')
const viewMode = ref('edit') // 'edit' | 'preview'

const skills = ref([])
const builtinSkills = ref([])
const currentSkill = ref(null)
const treeData = ref([])
const selectedTreeKeys = ref([])
const expandedKeys = ref([])
const selectedPath = ref('')
const selectedIsDir = ref(false)
const fileContent = ref('')
const originalFileContent = ref('')

const createModalVisible = ref(false)
const remoteInstallModalVisible = ref(false)
const createForm = reactive({ path: '', isDir: false, content: '' })
const remoteInstallForm = reactive({
  source: 'https://github.com/anthropics/skills',
  skills: []
})
const remoteSkillOptions = ref([])
const remoteInstallProgress = reactive({
  visible: false,
  total: 0,
  completed: 0,
  success: 0,
  failed: 0,
  currentSkill: ''
})
const remoteInstallResults = reactive({
  success: [],
  failed: []
})
const dependencyOptions = reactive({ tools: [], mcps: [], skills: [] })
const dependencyForm = reactive({
  tool_dependencies: [],
  mcp_dependencies: [],
  skill_dependencies: []
})

const matchesSearch = (skill) => {
  if (!searchQuery.value) return true
  const q = searchQuery.value.toLowerCase()
  return skill.name.toLowerCase().includes(q) || skill.slug.toLowerCase().includes(q)
}

const installedSkillCards = computed(() => {
  const builtinInstalledMap = new Map(
    (builtinSkills.value || [])
      .filter((skill) => skill.status !== 'not_installed')
      .map((skill) => [
        skill.slug,
        {
          ...skill,
          sourceType: 'builtin',
          sourceLabel: 'Built-in',
          statusLabel: skill.status === 'update_available' ? 'Update Available' : 'Installed',
          statusTone: skill.status === 'update_available' ? 'warning' : 'default'
        }
      ])
  )

  const importedInstalled = (skills.value || [])
    .filter((skill) => !builtinInstalledMap.has(skill.slug))
    .map((skill) => ({
      ...skill,
      sourceType: 'imported',
      sourceLabel: 'Imported',
      statusLabel: 'Uploaded',
      statusTone: 'default'
    }))

  return [...builtinInstalledMap.values(), ...importedInstalled]
})

const filteredInstalledSkills = computed(() => installedSkillCards.value.filter(matchesSearch))

const filteredUninstalledBuiltinSkills = computed(() => {
  return (builtinSkills.value || []).filter(
    (skill) => skill.status === 'not_installed' && matchesSearch(skill)
  )
})

const isInstalledSkill = computed(() => {
  return !!(
    currentSkill.value &&
    (currentSkill.value.installed_record || currentSkill.value.dir_path)
  )
})

const isBuiltinInstalledSkill = computed(() => {
  return !!(
    isInstalledSkill.value &&
    (currentSkill.value?.is_builtin || currentSkill.value?.installed_record)
  )
})

const currentSkillStatusLabel = computed(() => {
  const skill = currentSkill.value
  if (!skill) return ''
  if (skill.is_builtin_spec) {
    if (skill.status === 'not_installed') return 'Not Installed'
    if (skill.status === 'update_available') return 'Update Available'
    return 'Installed'
  }
  if (skill.is_builtin) return 'Installed'
  return 'Uploaded'
})

const currentSkillStatusTone = computed(() => {
  return currentSkill.value?.status === 'update_available' ? 'warning' : 'default'
})

const canSave = computed(() => {
  if (!selectedPath.value || selectedIsDir.value) return false
  return fileContent.value !== originalFileContent.value
})

const isMarkdownFile = computed(() => {
  if (!selectedPath.value) return false
  return selectedPath.value.toLowerCase().endsWith('.md')
})

// 切换到非markdown文件时重置为编辑模式
watch(selectedPath, (newPath) => {
  if (newPath && !newPath.toLowerCase().endsWith('.md')) {
    viewMode.value = 'edit'
  }
})

const toolDependencyOptions = computed(() =>
  (dependencyOptions.tools || []).map((i) =>
    typeof i === 'object' ? { label: i.name, value: i.id } : { label: i, value: i }
  )
)
const mcpDependencyOptions = computed(() =>
  (dependencyOptions.mcps || []).map((i) => ({ label: i, value: i }))
)
const skillDependencyOptions = computed(() =>
  (dependencyOptions.skills || [])
    .filter((s) => s !== currentSkill.value?.slug)
    .map((i) => ({ label: i, value: i }))
)
const filteredRemoteSkillOptions = computed(() =>
  remoteSkillOptions.value.map((item) => ({
    value: item.name,
    label: item.description ? `${item.name} - ${item.description}` : item.name
  }))
)
const remoteInstallStatusText = computed(() => {
  if (!remoteInstallProgress.visible || !remoteInstallProgress.total) return ''
  const progressText = `[${remoteInstallProgress.completed}/${remoteInstallProgress.total}]`
  const currentSkill = remoteInstallProgress.currentSkill || ''
  const failedText =
    remoteInstallProgress.failed > 0 ? `, ${remoteInstallProgress.failed} failed` : ''
  return `${progressText} ${currentSkill}${failedText}`.trim()
})
const filterRemoteSkillOption = (input, option) => {
  const keyword = input.trim().toLowerCase()
  if (!keyword) return true
  const value = String(option?.value || '').toLowerCase()
  const label = String(option?.label || '').toLowerCase()
  return value.includes(keyword) || label.includes(keyword)
}

const normalizeRemoteSkillNames = (skills) => {
  const seen = new Set()
  return (skills || []).reduce((acc, skill) => {
    const normalized = String(skill || '').trim()
    if (!normalized || seen.has(normalized)) return acc
    seen.add(normalized)
    acc.push(normalized)
    return acc
  }, [])
}

const resetRemoteInstallState = () => {
  remoteInstallProgress.visible = false
  remoteInstallProgress.total = 0
  remoteInstallProgress.completed = 0
  remoteInstallProgress.success = 0
  remoteInstallProgress.failed = 0
  remoteInstallProgress.currentSkill = ''
  remoteInstallResults.success = []
  remoteInstallResults.failed = []
}

const normalizeTree = (nodes) =>
  (nodes || []).map((node) => ({
    title: node.name,
    key: node.path,
    isLeaf: !node.is_dir,
    path: node.path,
    is_dir: node.is_dir,
    children: node.is_dir ? normalizeTree(node.children || []) : undefined
  }))

const resetFileState = () => {
  selectedPath.value = ''
  selectedIsDir.value = false
  selectedTreeKeys.value = []
  expandedKeys.value = []
  fileContent.value = ''
  originalFileContent.value = ''
  viewMode.value = 'preview'
}

const expandAllKeys = (nodes) =>
  nodes.flatMap((node) => (node.is_dir ? [node.key, ...expandAllKeys(node.children || [])] : []))

const fetchSkills = async () => {
  loading.value = true
  try {
    const [skillResult, builtinResult] = await Promise.all([
      skillApi.listSkills(),
      skillApi.listBuiltinSkills()
    ])
    skills.value = skillResult?.data || []
    builtinSkills.value = (builtinResult?.data || []).map((item) => ({
      ...item,
      ...(item.installed_record || {}),
      is_builtin_spec: true
    }))

    // Select first skill and load SKILL.md by default
    const preferredList = filteredInstalledSkills.value.length
      ? filteredInstalledSkills.value
      : filteredUninstalledBuiltinSkills.value
    if (!currentSkill.value && preferredList.length > 0) {
      await selectSkill(preferredList[0])
    } else if (currentSkill.value) {
      const latest =
        builtinSkills.value.find((i) => i.slug === currentSkill.value.slug) ||
        skills.value.find((i) => i.slug === currentSkill.value.slug)
      if (latest) {
        currentSkill.value = latest
        syncDependencyFormFromSkill(latest.installed_record || latest)
      } else {
        currentSkill.value = null
        treeData.value = []
        resetFileState()
      }
    }
    await fetchDependencyOptions()
  } catch {
    message.error('Failed to load')
  } finally {
    loading.value = false
  }
}

const fetchDependencyOptions = async () => {
  try {
    const result = await skillApi.getSkillDependencyOptions()
    const data = result?.data || {}
    dependencyOptions.tools = data.tools || []
    dependencyOptions.mcps = data.mcps || []
    dependencyOptions.skills = data.skills || []
  } catch {
    // ignore error
  }
}

const syncDependencyFormFromSkill = (skillRecord) => {
  dependencyForm.tool_dependencies = [...(skillRecord?.tool_dependencies || [])]
  dependencyForm.mcp_dependencies = [...(skillRecord?.mcp_dependencies || [])]
  dependencyForm.skill_dependencies = [...(skillRecord?.skill_dependencies || [])]
}

const reloadTree = async () => {
  if (!currentSkill.value || !isInstalledSkill.value) return
  loading.value = true
  try {
    const result = await skillApi.getSkillTree(currentSkill.value.slug)
    const normalized = normalizeTree(result?.data || [])
    treeData.value = normalized
    expandedKeys.value = expandAllKeys(normalized)
  } catch {
    message.error('Failed to load directory tree')
  } finally {
    loading.value = false
  }
}

const loadSkillFile = async (slug, path = 'SKILL.md') => {
  try {
    const fileResult = await skillApi.getSkillFile(slug, path)
    const content = fileResult?.data?.content || ''
    fileContent.value = content
    originalFileContent.value = content
    selectedPath.value = path
    selectedIsDir.value = false
    selectedTreeKeys.value = [path]
  } catch {
    // Ignore if file doesn't exist
  }
}

const selectSkill = async (record) => {
  currentSkill.value = record
  resetFileState()
  syncDependencyFormFromSkill(record.installed_record || record)

  if (!record.installed_record && !record.dir_path) {
    treeData.value = []
    return
  }

  // Run in parallel: load tree and get SKILL.md
  await Promise.all([reloadTree(), loadSkillFile(record.slug)])
}

const handleTreeSelect = async (keys, info) => {
  if (!keys?.length) {
    resetFileState()
    return
  }
  const node = info?.node || {}
  const path = node.path || node.key
  const isDir = !!node.is_dir
  selectedTreeKeys.value = [path]
  selectedPath.value = path
  selectedIsDir.value = isDir
  if (isDir) {
    fileContent.value = ''
    originalFileContent.value = ''
    return
  }
  try {
    const result = await skillApi.getSkillFile(currentSkill.value.slug, path)
    const content = result?.data?.content || ''
    fileContent.value = content
    originalFileContent.value = content
  } catch {
    message.error('Failed to read file')
  }
}

const saveCurrentFile = async () => {
  if (
    !currentSkill.value ||
    !selectedPath.value ||
    selectedIsDir.value ||
    isBuiltinInstalledSkill.value
  )
    return
  savingFile.value = true
  try {
    await skillApi.updateSkillFile(currentSkill.value.slug, {
      path: selectedPath.value,
      content: fileContent.value
    })
    originalFileContent.value = fileContent.value
    message.success('Saved')
    if (selectedPath.value === 'SKILL.md') await fetchSkills()
  } catch {
    message.error('Failed to save')
  } finally {
    savingFile.value = false
  }
}

const handleInstallBuiltin = async (record) => {
  if (!record?.slug) return
  loading.value = true
  try {
    await skillApi.installBuiltinSkill(record.slug)
    await fetchSkills()
    const latest = builtinSkills.value.find((item) => item.slug === record.slug)
    if (latest) await selectSkill(latest)
    message.success('Installed successfully')
  } catch (error) {
    message.error(error?.response?.data?.detail || error.message || 'Installation failed')
  } finally {
    loading.value = false
  }
}

const handleUpdateBuiltin = async (record) => {
  if (!record?.slug) return
  loading.value = true
  try {
    await skillApi.updateBuiltinSkill(record.slug, false)
    await fetchSkills()
    const latest = builtinSkills.value.find((item) => item.slug === record.slug)
    if (latest) await selectSkill(latest)
    message.success('Updated successfully')
  } catch (error) {
    if (error.response?.data?.detail?.needs_confirm) {
      loading.value = false
      Modal.confirm({
        title: 'Confirm Overwrite Update?',
        content: 'Modifications detected in this skill. Updating will overwrite your changes. Continue?',
        okText: 'Continue Update',
        cancelText: 'Cancel',
        onOk: async () => {
          loading.value = true
          try {
            await skillApi.updateBuiltinSkill(record.slug, true)
            await fetchSkills()
            const latest = builtinSkills.value.find((item) => item.slug === record.slug)
            if (latest) await selectSkill(latest)
            message.success('Updated successfully')
          } catch (forceError) {
            message.error(forceError?.response?.data?.detail || forceError.message || 'Update failed')
          } finally {
            loading.value = false
          }
        }
      })
      return
    }
    message.error(error?.response?.data?.detail || error.message || 'Update failed')
  } finally {
    loading.value = false
  }
}

const openCreateModal = (isDir) => {
  if (!currentSkill.value) return
  createForm.path = ''
  createForm.content = ''
  createForm.isDir = isDir
  createModalVisible.value = true
}

const handleCreateNode = async () => {
  if (!currentSkill.value || !createForm.path.trim() || isBuiltinInstalledSkill.value) return
  creatingNode.value = true
  try {
    await skillApi.createSkillFile(currentSkill.value.slug, {
      path: createForm.path.trim(),
      is_dir: createForm.isDir,
      content: createForm.content
    })
    createModalVisible.value = false
    await reloadTree()
    message.success('Created successfully')
  } catch {
    message.error('Creation failed')
  } finally {
    creatingNode.value = false
  }
}

const confirmDeleteSkill = (targetSkill = null) => {
  const target = targetSkill || currentSkill.value
  if (!target) return

  const installed = !!(
    target &&
    (target.installed_record || target.dir_path || target.is_builtin || target.sourceType)
  )
  if (!installed) return

  const isBuiltinTarget = !!(
    target?.is_builtin ||
    target?.installed_record ||
    target?.sourceType === 'builtin'
  )
  const actionText = isBuiltinTarget ? 'uninstall' : 'delete'
  const actionDoneText = isBuiltinTarget ? 'Uninstalled' : 'Deleted'
  const detailText = isBuiltinTarget
    ? 'Uninstalling will remove installed files and database records, but you can reinstall it from "Uninstalled Skills".'
    : 'Deletion is irreversible. All files and configurations will be permanently lost.'
  Modal.confirm({
    title: `Confirm to ${actionText} skill "${target.slug}"?`,
    content: detailText,
    okText: `Confirm`,
    okType: 'danger',
    cancelText: 'Cancel',
    onOk: async () => {
      try {
        await skillApi.deleteSkill(target.slug)
        message.success(`${actionDoneText} successfully`)
        if (currentSkill.value?.slug === target.slug) {
          currentSkill.value = null
          treeData.value = []
          resetFileState()
        }
        await fetchSkills()
      } catch {
        message.error(`Failed to ${actionText}`)
      }
    }
  })
}

const handleExport = async () => {
  if (!currentSkill.value || !isInstalledSkill.value) return
  try {
    const response = await skillApi.exportSkill(currentSkill.value.slug)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${currentSkill.value.slug}.zip`
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    message.error('Export failed')
  }
}

const handleImportUpload = async ({ file, onSuccess, onError }) => {
  importing.value = true
  try {
    const result = await skillApi.importSkillZip(file)
    message.success('Import completed')
    await fetchSkills()
    const imported = result?.data
    if (imported?.slug) {
      const record = skills.value.find((i) => i.slug === imported.slug)
      if (record) await selectSkill(record)
    }
    onSuccess?.(result)
  } catch (e) {
    message.error('Import failed')
    onError?.(e)
  } finally {
    importing.value = false
  }
}

const handleListRemoteSkills = async () => {
  const source = remoteInstallForm.source.trim()
  if (!source) {
    message.warning('Please enter source repository')
    return
  }
  listingRemoteSkills.value = true
  try {
    const result = await skillApi.listRemoteSkills(source)
    remoteSkillOptions.value = result?.data || []
    remoteInstallForm.skills = normalizeRemoteSkillNames(remoteInstallForm.skills)
    if (!remoteSkillOptions.value.length) {
      message.warning('No installable Skills found')
      return
    }
    message.success(`Found ${remoteSkillOptions.value.length} Skills`)
  } catch (error) {
    message.error(error?.response?.data?.detail || error.message || 'Failed to get remote Skills')
  } finally {
    listingRemoteSkills.value = false
  }
}

const handleInstallRemoteSkill = async () => {
  const source = remoteInstallForm.source.trim()
  const skillsToInstall = normalizeRemoteSkillNames(remoteInstallForm.skills)
  if (!source || !skillsToInstall.length) {
    message.warning('Please select source repository and Skill names')
    return
  }
  remoteInstallForm.skills = skillsToInstall
  resetRemoteInstallState()
  installingRemoteSkill.value = true
  remoteInstallProgress.visible = true
  remoteInstallProgress.total = skillsToInstall.length
  let lastInstalledSlug = ''
  try {
    for (const skill of skillsToInstall) {
      remoteInstallProgress.currentSkill = skill
      try {
        const result = await skillApi.installRemoteSkill({ source, skill })
        const installed = result?.data
        const installedSlug = installed?.slug || skill
        remoteInstallResults.success.push(installedSlug)
        remoteInstallProgress.success += 1
        lastInstalledSlug = installedSlug
      } catch (error) {
        remoteInstallResults.failed.push({
          skill,
          error: error?.response?.data?.detail || error.message || 'Remote Skill installation failed'
        })
        remoteInstallProgress.failed += 1
      } finally {
        remoteInstallProgress.completed += 1
      }
    }
    remoteInstallProgress.currentSkill = ''
    await fetchSkills()
    if (lastInstalledSlug) {
      const record =
        skills.value.find((item) => item.slug === lastInstalledSlug) ||
        builtinSkills.value.find((item) => item.slug === lastInstalledSlug)
      if (record) await selectSkill(record)
    }
    if (remoteInstallResults.failed.length === 0) {
      remoteInstallModalVisible.value = false
      message.success(`Successfully installed ${remoteInstallResults.success.length} remote Skills`)
      resetRemoteInstallState()
      remoteInstallForm.skills = []
      return
    }
    message.warning(
      `Remote Skills installation complete. Success: ${remoteInstallResults.success.length}, Failed: ${remoteInstallResults.failed.length}`
    )
  } catch (error) {
    message.error(error?.response?.data?.detail || error.message || 'Remote Skill installation failed')
  } finally {
    remoteInstallProgress.currentSkill = ''
    installingRemoteSkill.value = false
  }
}

const openRemoteInstallModal = () => {
  if (!remoteInstallModalVisible.value) {
    remoteInstallForm.skills = []
    resetRemoteInstallState()
  }
  remoteInstallModalVisible.value = true
}

watch(remoteInstallModalVisible, (visible) => {
  if (!visible && !installingRemoteSkill.value) {
    remoteInstallForm.skills = []
    resetRemoteInstallState()
  }
})

const saveDependencies = async () => {
  if (!currentSkill.value || !isInstalledSkill.value) return
  savingDependencies.value = true
  try {
    const result = await skillApi.updateSkillDependencies(currentSkill.value.slug, {
      tool_dependencies: dependencyForm.tool_dependencies,
      mcp_dependencies: dependencyForm.mcp_dependencies,
      skill_dependencies: dependencyForm.skill_dependencies
    })
    const updated = result?.data
    if (updated) {
      currentSkill.value = updated
      syncDependencyFormFromSkill(updated)
    }
    await fetchSkills()
    message.success('Dependencies updated')
  } catch {
    message.error('Update failed')
  } finally {
    savingDependencies.value = false
  }
}

onMounted(fetchSkills)

// Expose methods to parent components
defineExpose({
  fetchSkills,
  handleImportUpload,
  openRemoteInstallModal
})
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';

.builtin-uninstalled-state {
  padding: 24px;
  h3 {
    margin: 0 0 8px;
    font-size: 16px;
  }
  p {
    margin: 0 0 16px;
    color: var(--gray-500);
  }
}

.workspace {
  display: flex;
  flex: 1;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.remote-install-panel {
  background: linear-gradient(180deg, var(--gray-0) 0%, var(--gray-50) 100%);
  border: 1px solid @border-color;
  border-radius: 12px;
  padding: 16px;

  &.modal-mode {
    border: none;
    border-radius: 0;
    padding: 0;
    background: transparent;
  }

  .panel-header-text {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;

    .title {
      font-size: 14px;
      font-weight: 600;
      color: var(--gray-900);
    }

    .desc {
      font-size: 12px;
      color: var(--gray-500);
    }
  }

  .remote-install-form {
    :deep(.ant-form-item) {
      margin-bottom: 12px;
    }
  }

  .remote-install-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .remote-install-status {
    min-width: 0;
    flex: 1;
    font-size: 12px;
    color: var(--gray-600);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .remote-skill-hints {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }

  .remote-skill-summary {
    margin-top: 12px;
    font-size: 12px;
    color: var(--gray-500);
  }
}

/* 文件 tree */
.tree-container {
  width: 240px;
  border-right: 1px solid @border-color;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;

  .tree-header {
    padding: 10px 12px 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    .label {
      font-size: 12px;
      font-weight: 600;
      color: var(--gray-500);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .tree-actions {
      display: flex;
      gap: 4px;
      button {
        background: none;
        border: none;
        padding: 2px;
        cursor: pointer;
        color: var(--gray-500);
        display: flex;
        align-items: center;
        &:hover {
          color: var(--gray-900);
        }
      }
    }
  }

  .tree-content {
    flex: 1;
    overflow-y: auto;
    height: 100%;
    padding: 8px 0;
  }
}

/* 编辑器 */
.editor-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;

  .editor-header {
    padding: 8px 16px 4px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background-color: var(--gray-0);
    flex-shrink: 0;

    .current-path {
      display: flex;
      align-items: center;
      gap: 8px;
      font-family: monospace;
      font-size: 12px;
      color: var(--gray-500);
      .save-hint {
        color: var(--color-warning-500);
        font-size: 10px;
        margin-left: 4px;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .view-toggle-btn {
      background-color: var(--gray-100);
      border-color: var(--gray-300);
      &:hover {
        background-color: var(--gray-200);
        border-color: var(--gray-400);
      }
    }
  }

  .editor-main {
    flex: 1;
    min-height: 0;
    background-color: var(--gray-0);
    display: flex;
    flex-direction: column;
  }

  .editor-main :deep(.ant-empty) {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .editor-main :deep(textarea) {
    flex: 1;
    min-height: 0;
  }

  .pure-editor {
    width: 100%;
    height: 100%;
    border: none;
    resize: none;
    padding: 16px;
    font-family: 'Fira Code', 'Monaco', monospace;
    font-size: 13px;
    line-height: 1.6;
    &:focus {
      outline: none;
    }
  }

  .markdown-preview {
    flex: 1;
    height: 100%;
    overflow-y: auto;
    :deep(.md-editor) {
      height: 100%;
      background: var(--gray-0);
    }
    :deep(.md-editor-preview-wrapper) {
      padding: 16px 20px;
    }
  }
}

/* 依赖配置 */
.config-view {
  padding: 16px;
  flex: 1;
  overflow-y: auto;
  .config-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 32px;
    flex-shrink: 0;
    .text {
      h3 {
        margin: 0 0 4px 0;
        font-size: 16px;
        font-weight: 600;
      }
      p {
        margin: 0;
        color: var(--gray-500);
        font-size: 13px;
      }
    }
  }
  .config-form {
    max-width: 600px;
    :deep(.ant-form-item-label label) {
      font-weight: 500;
      font-size: 13px;
    }
  }
}

.mt-40 {
  margin-top: 40px;
}
.pt-12 {
  padding-top: 12px;
}

@media (max-width: 1000px) {
  .sidebar-list {
    width: 220px;
  }
  .tree-container {
    width: 180px;
  }
}
</style>
