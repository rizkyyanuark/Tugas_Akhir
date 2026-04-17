<template>
  <div class="file-table-container">
    <div class="panel-header">
      <div class="upload-btn-group">
        <a-button type="primary" size="small" class="upload-btn" @click="showAddFilesModal()">
          <FileUp size="14" />
          Upload
        </a-button>

        <a-button
          class="panel-action-btn"
          type="text"
          size="small"
          @click="showCreateFolderModal"
          title="Create Folder"
        >
          <template #icon><FolderPlus size="16" /></template>
        </a-button>
      </div>
      <div class="panel-actions">
        <a-input
          v-model:value="filenameFilter"
          placeholder="Search"
          size="small"
          class="action-searcher"
          allow-clear
          @change="onFilterChange"
        >
          <template #prefix>
            <Search size="14" style="color: var(--gray-400)" />
          </template>
        </a-input>

        <a-dropdown trigger="click">
          <a-button
            type="text"
            class="panel-action-btn"
            :class="{ active: sortField !== 'filename' }"
            title="Sort"
          >
            <template #icon><ArrowUpDown size="16" /></template>
          </a-button>
          <template #overlay>
            <a-menu :selectedKeys="[sortField]" @click="handleSortMenuClick">
              <a-menu-item v-for="opt in sortOptions" :key="opt.value">
                {{ opt.label }}
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>

        <a-dropdown trigger="click">
          <a-button
            type="text"
            class="panel-action-btn"
            :class="{ active: statusFilter !== 'all' }"
            title="Filter Status"
          >
            <template #icon><Filter size="16" /></template>
          </a-button>
          <template #overlay>
            <a-menu :selectedKeys="[statusFilter]" @click="handleStatusMenuClick">
              <a-menu-item key="all">All Statuses</a-menu-item>
              <a-menu-item v-for="opt in statusOptions" :key="opt.value">
                {{ opt.label }}
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>

        <a-button
          type="text"
          @click="handleRefresh"
          :loading="refreshing"
          title="Refresh"
          class="panel-action-btn"
        >
          <template #icon><RotateCw size="16" /></template>
        </a-button>
        <a-button
          type="text"
          @click="toggleSelectionMode"
          title="Multi Select"
          class="panel-action-btn"
          :class="{ active: isSelectionMode }"
        >
          <template #icon><CheckSquare size="16" /></template>
        </a-button>
        <!-- <a-button
          @click="toggleAutoRefresh"
          size="small"
          :type="autoRefresh ? 'primary' : 'default'"
          title="Auto refresh file status"
          class="auto-refresh-btn panel-action-btn"
        >
          Auto
        </a-button> -->
        <a-button
          type="text"
          @click="toggleRightPanel"
          title="Toggle Right Panel"
          class="panel-action-btn expand"
          :class="{ expanded: props.rightPanelVisible }"
        >
          <template #icon><ChevronLast size="16" /></template>
        </a-button>
      </div>
    </div>

    <div class="batch-actions" v-if="isSelectionMode">
      <div class="batch-info">
        <a-checkbox
          :checked="isAllSelected"
          :indeterminate="isPartiallySelected"
          @change="onSelectAllChange"
          style="margin-right: 8px"
        />
        <span>{{ selectedRowKeys.length }} items</span>
      </div>
      <div style="display: flex; gap: 2px">
        <a-button
          type="link"
          @click="handleBatchParse"
          :loading="batchParsing"
          :disabled="!canBatchParse"
          :icon="h(FileText, { size: 16 })"
        >
          Parse Selected
        </a-button>
        <a-button
          type="link"
          @click="handleBatchIndex"
          :loading="batchIndexing"
          :disabled="!canBatchIndex"
          :icon="h(Database, { size: 16 })"
        >
          Index Selected
        </a-button>
        <a-button
          type="link"
          danger
          @click="handleBatchDelete"
          :loading="batchDeleting"
          :disabled="!canBatchDelete"
          :icon="h(Trash2, { size: 16 })"
        >
          Delete Selected
        </a-button>
      </div>
    </div>

    <!-- Index/Reindex parameter modal -->
    <a-modal
      v-model:open="indexConfigModalVisible"
      :title="indexConfigModalTitle"
      :confirm-loading="indexConfigModalLoading"
      width="600px"
    >
      <template #footer>
        <a-button key="back" @click="handleIndexConfigCancel">Cancel</a-button>
        <a-button key="submit" type="primary" @click="handleIndexConfigConfirm">Confirm</a-button>
      </template>
      <div class="index-params">
        <ChunkParamsConfig
          :temp-chunk-params="indexParams"
          :show-qa-split="true"
          :show-chunk-size-overlap="!isLightRAG"
          :show-preset="true"
          :allow-preset-follow-default="true"
          :database-preset-id="store.database?.additional_params?.chunk_preset_id || 'general'"
        />
      </div>
    </a-modal>

    <!-- Create folder modal -->
    <a-modal
      v-model:open="createFolderModalVisible"
      title="Create Folder"
      :confirm-loading="createFolderLoading"
      @ok="handleCreateFolder"
    >
      <a-input
        v-model:value="newFolderName"
        placeholder="Enter folder name"
        @pressEnter="handleCreateFolder"
      />
    </a-modal>

    <a-table
      :columns="columnsCompact"
      :data-source="paginatedFiles"
      row-key="file_id"
      class="my-table"
      size="small"
      :show-header="false"
      :pagination="tablePagination"
      @change="handleTableChange"
      v-model:expandedRowKeys="expandedRowKeys"
      :custom-row="customRow"
      :row-selection="
        isSelectionMode
          ? {
              selectedRowKeys: selectedRowKeys,
              onChange: onSelectChange,
              getCheckboxProps: getCheckboxProps
            }
          : null
      "
      :locale="{
        emptyText: emptyText
      }"
    >
      <template #bodyCell="{ column, text, record }">
        <div v-if="column.key === 'filename'">
          <template v-if="record.is_folder">
            <span class="folder-row" @click="toggleExpand(record)">
              <component
                :is="
                  expandedRowKeys.includes(record.file_id) ? h(FolderOpenFilled) : h(FolderFilled)
                "
                style="margin-right: 8px; color: #ffb800; font-size: 16px"
              />
              {{ record.filename }}
            </span>
          </template>
          <a-popover
            v-else
            placement="right"
            overlayClassName="file-info-popover"
            :mouseEnterDelay="0.5"
          >
            <template #content>
              <div class="file-info-card">
                <div class="info-row">
                  <span class="label">ID:</span> <span class="value">{{ record.file_id }}</span>
                </div>
                <div class="info-row">
                  <span class="label">Status:</span>
                  <span class="value">{{ getStatusText(record.status) }}</span>
                </div>
                <div class="info-row">
                  <span class="label">Time:</span>
                  <span class="value">{{ formatRelativeTime(record.created_at) }}</span>
                </div>
                <div v-if="record.error_message" class="info-row error">
                  <span class="label">Error:</span>
                  <span class="value">{{ record.error_message }}</span>
                </div>
              </div>
            </template>
            <a-button class="main-btn" type="link" @click="openFileDetail(record)">
              <component
                :is="getFileIcon(record.displayName || text)"
                :style="{
                  marginRight: '0',
                  color: getFileIconColor(record.displayName || text),
                  fontSize: '16px'
                }"
              />
              {{ record.displayName || text }}
            </a-button>
          </a-popover>
        </div>
        <span v-else-if="column.key === 'type'">
          <span v-if="!record.is_folder" :class="['span-type', text]">{{
            text?.toUpperCase()
          }}</span>
        </span>
        <div
          v-else-if="column.key === 'status'"
          style="display: flex; align-items: center; justify-content: flex-end"
        >
          <template v-if="!record.is_folder">
            <a-tooltip :title="getStatusText(text)">
              <span
                v-if="text === 'done' || text === 'indexed'"
                style="color: var(--color-success-500)"
                ><CheckCircleFilled
              /></span>
              <span
                v-else-if="
                  text === 'failed' || text === 'error_parsing' || text === 'error_indexing'
                "
                style="color: var(--color-error-500)"
                ><CloseCircleFilled
              /></span>
              <span
                v-else-if="text === 'processing' || text === 'parsing' || text === 'indexing'"
                style="color: var(--color-info-500)"
                ><HourglassFilled
              /></span>
              <span
                v-else-if="text === 'waiting' || text === 'uploaded'"
                style="color: var(--color-warning-500)"
                ><ClockCircleFilled
              /></span>
              <span v-else-if="text === 'parsed'" style="color: var(--color-primary-500)"
                ><FileTextFilled
              /></span>
              <span v-else>{{ text }}</span>
            </a-tooltip>
          </template>
        </div>

        <div v-else-if="column.key === 'action'" class="table-row-actions">
          <a-popover
            placement="bottomRight"
            trigger="click"
            overlayClassName="file-action-popover"
            v-model:open="popoverVisibleMap[record.file_id]"
          >
            <template #content>
              <div class="file-action-list">
                <template v-if="record.is_folder">
                  <a-button type="text" block @click="showCreateFolderModal(record.file_id)">
                    <template #icon><component :is="h(FolderPlus)" size="14" /></template>
                    New Subfolder
                  </a-button>
                  <a-button type="text" block danger @click="handleDeleteFolder(record)">
                    <template #icon><component :is="h(Trash2)" size="14" /></template>
                    Delete Folder
                  </a-button>
                </template>
                <template v-else>
                  <a-button
                    type="text"
                    block
                    @click="handleDownloadFile(record)"
                    :disabled="
                      lock ||
                      record.file_type === 'url' ||
                      !['done', 'indexed', 'parsed', 'error_indexing'].includes(record.status)
                    "
                  >
                    <template #icon><component :is="h(Download)" size="14" /></template>
                    Download File
                  </a-button>

                  <!-- Parse Action -->
                  <a-button
                    v-if="record.status === 'uploaded' || record.status === 'error_parsing'"
                    type="text"
                    block
                    @click="handleParseFile(record)"
                    :disabled="lock"
                  >
                    <template #icon><component :is="h(FileText)" size="14" /></template>
                    {{ record.status === 'error_parsing' ? 'Retry Parse' : 'Parse File' }}
                  </a-button>

                  <!-- Index Action -->
                  <a-button
                    v-if="record.status === 'parsed' || record.status === 'error_indexing'"
                    type="text"
                    block
                    @click="handleIndexFile(record)"
                    :disabled="lock"
                  >
                    <template #icon><component :is="h(Database)" size="14" /></template>
                    {{ record.status === 'error_indexing' ? 'Retry Index' : 'Index' }}
                  </a-button>

                  <!-- Reindex Action -->
                  <a-button
                    v-if="!isLightRAG && (record.status === 'done' || record.status === 'indexed')"
                    type="text"
                    block
                    @click="handleReindexFile(record)"
                    :disabled="lock"
                  >
                    <template #icon><component :is="h(RotateCw)" size="14" /></template>
                    Reindex
                  </a-button>

                  <a-button
                    type="text"
                    block
                    danger
                    @click="handleDeleteFile(record.file_id)"
                    :disabled="
                      lock || ['processing', 'parsing', 'indexing'].includes(record.status)
                    "
                  >
                    <template #icon><component :is="h(Trash2)" size="14" /></template>
                    Delete File
                  </a-button>
                </template>
              </div>
            </template>
            <a-button type="text" :icon="h(Ellipsis)" class="action-trigger-btn" />
          </a-popover>
        </div>
        <span v-else>{{ text }}</span>
      </template>
    </a-table>
  </div>
</template>

<script setup>
import { ref, computed, h } from 'vue'
import { useDatabaseStore } from '@/stores/database'
import { message, Modal } from 'ant-design-vue'
import { documentApi } from '@/apis/knowledge_api'
import {
  CheckCircleFilled,
  HourglassFilled,
  CloseCircleFilled,
  ClockCircleFilled,
  FolderFilled,
  FolderOpenFilled,
  FileTextFilled
} from '@ant-design/icons-vue'
import {
  Trash2,
  Download,
  RotateCw,
  ChevronLast,
  Ellipsis,
  FolderPlus,
  CheckSquare,
  FileText,
  Database,
  FileUp,
  Search,
  Filter,
  ArrowUpDown
} from 'lucide-vue-next'

const store = useDatabaseStore()

const sortField = ref('filename')
const sortOptions = [
  { label: 'File Name', value: 'filename' },
  { label: 'Created At', value: 'created_at' },
  { label: 'Status', value: 'status' }
]

const handleSortMenuClick = (e) => {
  sortField.value = e.key
  // Reset to first page when sort changes
  paginationConfig.value.current = 1
}

const handleStatusMenuClick = (e) => {
  statusFilter.value = e.key
  // Reset to first page when status filter changes
  paginationConfig.value.current = 1
}

// Status text mapping
const getStatusText = (status) => {
  const map = {
    uploaded: 'Uploaded',
    parsing: 'Parsing',
    parsed: 'Parsed',
    error_parsing: 'Parse Failed',
    indexing: 'Indexing',
    indexed: 'Indexed',
    error_indexing: 'Index Failed',
    done: 'Indexed',
    failed: 'Index Failed',
    processing: 'Processing',
    waiting: 'Waiting'
  }
  return map[status] || status
}

const props = defineProps({
  rightPanelVisible: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['showAddFilesModal', 'toggleRightPanel'])

const files = computed(() => Object.values(store.database.files || {}))
const isLightRAG = computed(() => store.database?.kb_type?.toLowerCase() === 'lightrag')
const refreshing = computed(() => store.state.refrashing)
const lock = computed(() => store.state.lock)
const batchDeleting = computed(() => store.state.batchDeleting)
const batchParsing = computed(() => store.state.chunkLoading)
const batchIndexing = computed(() => store.state.chunkLoading)
const selectedRowKeys = computed({
  get: () => store.selectedRowKeys,
  set: (keys) => (store.selectedRowKeys = keys)
})

const isSelectionMode = ref(false)

const allSelectableFiles = computed(() => {
  const nameFilter = filenameFilter.value.trim().toLowerCase()
  const status = statusFilter.value

  return files.value.filter((file) => {
    if (file.is_folder) return false
    // Follow getCheckboxProps logic
    if (lock.value || file.status === 'processing' || file.status === 'waiting') return false

    if (nameFilter || status !== 'all') {
      const nameMatch =
        !nameFilter || (file.filename && file.filename.toLowerCase().includes(nameFilter))
      const statusMatch =
        status === 'all' ||
        file.status === status ||
        (status === 'indexed' && file.status === 'done') ||
        (status === 'error_indexing' && file.status === 'failed')
      return nameMatch && statusMatch
    }
    return true
  })
})

const isAllSelected = computed(() => {
  const selectableIds = allSelectableFiles.value.map((f) => f.file_id)
  if (selectableIds.length === 0) return false
  return selectableIds.every((id) => selectedRowKeys.value.includes(id))
})

const isPartiallySelected = computed(() => {
  const selectableIds = allSelectableFiles.value.map((f) => f.file_id)
  const selectedCount = selectableIds.filter((id) => selectedRowKeys.value.includes(id)).length
  return selectedCount > 0 && selectedCount < selectableIds.length
})

const onSelectAllChange = (e) => {
  if (e.target.checked) {
    selectedRowKeys.value = allSelectableFiles.value.map((f) => f.file_id)
  } else {
    selectedRowKeys.value = []
  }
}

const expandedRowKeys = ref([])

const popoverVisibleMap = ref({})
const closePopover = (fileId) => {
  if (fileId) {
    popoverVisibleMap.value[fileId] = false
  }
}

// Create folder state
const createFolderModalVisible = ref(false)
const newFolderName = ref('')
const createFolderLoading = ref(false)
const currentParentId = ref(null)

const showCreateFolderModal = (parentId = null) => {
  if (typeof parentId === 'string') {
    closePopover(parentId)
  }
  newFolderName.value = ''
  // If parentId is an event object (from top button click), set to null
  if (parentId && typeof parentId === 'object') {
    parentId = null
  }
  currentParentId.value = parentId
  createFolderModalVisible.value = true
}

const toggleExpand = (record) => {
  if (!record.is_folder) return

  const index = expandedRowKeys.value.indexOf(record.file_id)
  if (index > -1) {
    expandedRowKeys.value.splice(index, 1)
  } else {
    expandedRowKeys.value.push(record.file_id)
  }
}

const toggleSelectionMode = () => {
  isSelectionMode.value = !isSelectionMode.value
  if (!isSelectionMode.value) {
    selectedRowKeys.value = []
  }
}

const handleCreateFolder = async () => {
  if (!newFolderName.value.trim()) {
    message.warning('Please enter a folder name')
    return
  }

  createFolderLoading.value = true
  try {
    await documentApi.createFolder(store.databaseId, newFolderName.value, currentParentId.value)
    message.success('Created successfully')
    createFolderModalVisible.value = false
    handleRefresh()
  } catch (error) {
    console.error(error)
    message.error('Creation failed: ' + (error.message || 'Unknown error'))
  } finally {
    createFolderLoading.value = false
  }
}

// Drag and drop logic
const customRow = (record) => {
  return {
    draggable: true,
    onClick: () => {
      console.log('Clicked file record:', record)
    },
    onDragstart: (event) => {
      // Check whether this is a real file/folder (exists in store)
      const files = store.database?.files || {}
      if (!files[record.file_id]) {
        event.preventDefault()
        return
      }

      event.dataTransfer.setData(
        'application/json',
        JSON.stringify({
          file_id: record.file_id,
          filename: record.filename
        })
      )
      event.dataTransfer.effectAllowed = 'move'
      // You can set a nicer drag image here
    },
    onDragover: (event) => {
      // Allow drop only into real folders
      if (record.is_folder) {
        const files = store.database?.files || {}
        // Ensure this is a real folder (has ID and exists in store)
        if (files[record.file_id]) {
          event.preventDefault()
          event.dataTransfer.dropEffect = 'move'
          event.currentTarget.classList.add('drop-over-folder')
        }
      }
    },
    onDragleave: (event) => {
      event.currentTarget.classList.remove('drop-over-folder')
    },
    onDrop: async (event) => {
      event.preventDefault()
      event.currentTarget.classList.remove('drop-over-folder')

      const data = event.dataTransfer.getData('application/json')
      if (!data) return

      try {
        const { file_id, filename } = JSON.parse(data)
        if (file_id === record.file_id) return

        // Confirm move
        Modal.confirm({
          title: 'Move File',
          content: `Are you sure you want to move "${filename}" to "${record.filename}"?`,
          onOk: async () => {
            try {
              await store.moveFile(file_id, record.file_id)
            } catch {
              // error handled in store
            }
          }
        })
      } catch (e) {
        console.error('Drop error:', e)
      }
    }
  }
}

// Index/reindex parameter state
const indexConfigModalVisible = ref(false)
const indexConfigModalLoading = computed(() => store.state.chunkLoading)
const indexConfigModalTitle = ref('Index Parameters')

const indexParams = ref({
  chunk_size: 1000,
  chunk_overlap: 200,
  qa_separator: '',
  chunk_preset_id: ''
})
const buildIndexParamsPayload = () => {
  const payload = {}
  if (indexParams.value.chunk_preset_id) {
    payload.chunk_preset_id = indexParams.value.chunk_preset_id
  }

  if (isLightRAG.value) {
    payload.qa_separator = indexParams.value.qa_separator || ''
    return payload
  }

  return {
    ...indexParams.value,
    ...payload
  }
}
const currentIndexFileIds = ref([])
const isBatchIndexOperation = ref(false)

// Pagination config
const paginationConfig = ref({
  current: 1,
  pageSize: 100,
  pageSizeOptions: ['100', '300', '500', '1000']
})

// Total file count
const totalFiles = computed(() => files.value.length)

// Whether to show pagination
const showPagination = computed(() => totalFiles.value > paginationConfig.value.pageSize)

// Paginated data
const paginatedFiles = computed(() => {
  const list = filteredFiles.value
  if (!showPagination.value) return list

  const start = (paginationConfig.value.current - 1) * paginationConfig.value.pageSize
  const end = start + paginationConfig.value.pageSize
  return list.slice(start, end)
})

// Table pagination config
const tablePagination = computed(() => ({
  current: paginationConfig.value.current,
  pageSize: paginationConfig.value.pageSize,
  total: filteredFiles.value.length,
  showSizeChanger: true,
  showTotal: (total) => `Total ${total} items`,
  pageSizeOptions: paginationConfig.value.pageSizeOptions,
  hideOnSinglePage: true
}))

// Handle table changes (pagination, page size)
const handleTableChange = (pagination) => {
  paginationConfig.value.current = pagination.current
  paginationConfig.value.pageSize = pagination.pageSize
}

// Filename filtering
const filenameFilter = ref('')
const statusFilter = ref('all')
const statusOptions = [
  { label: 'Uploaded', value: 'uploaded' },
  { label: 'Parsing', value: 'parsing' },
  { label: 'Parsed', value: 'parsed' },
  { label: 'Parse Failed', value: 'error_parsing' },
  { label: 'Indexing', value: 'indexing' },
  { label: 'Indexed', value: 'indexed' },
  { label: 'Index Failed', value: 'error_indexing' }
]

// Compact table column definitions
const columnsCompact = [
  {
    title: 'File Name',
    dataIndex: 'filename',
    key: 'filename',
    ellipsis: true,
    width: undefined, // Keep flexible to take remaining space
    sorter: (a, b) => {
      if (a.is_folder && !b.is_folder) return -1
      if (!a.is_folder && b.is_folder) return 1
      return (a.filename || '').localeCompare(b.filename || '')
    },
    sortDirections: ['ascend', 'descend']
  },
  {
    title: 'Status',
    dataIndex: 'status',
    key: 'status',
    width: 60,
    align: 'right',
    sorter: (a, b) => {
      const statusOrder = {
        done: 1,
        indexed: 1,
        processing: 2,
        indexing: 2,
        parsing: 2,
        waiting: 3,
        uploaded: 3,
        parsed: 3,
        failed: 4,
        error_indexing: 4,
        error_parsing: 4
      }
      return (statusOrder[a.status] || 5) - (statusOrder[b.status] || 5)
    },
    sortDirections: ['ascend', 'descend']
  },
  { title: '', key: 'action', dataIndex: 'file_id', width: 40, align: 'center' }
]

// Build file tree
const buildFileTree = (fileList) => {
  const nodeMap = new Map()
  const roots = []
  const processedIds = new Set()

  // 1. Initialize node map and ensure explicit folders have children
  fileList.forEach((file) => {
    const item = { ...file, displayName: file.filename }
    if (item.is_folder && !item.children) {
      item.children = []
    }
    nodeMap.set(item.file_id, item)
  })

  // 2. Resolve parent_id links (strong association)
  fileList.forEach((file) => {
    if (file.parent_id && nodeMap.has(file.parent_id)) {
      const parent = nodeMap.get(file.parent_id)
      const child = nodeMap.get(file.file_id)
      if (parent && child) {
        if (!parent.children) parent.children = []
        parent.children.push(child)
        processedIds.add(file.file_id)
      }
    }
  })

  // 3. Handle remaining items (roots or path parsing)
  fileList.forEach((file) => {
    if (processedIds.has(file.file_id)) return

    const item = nodeMap.get(file.file_id)
    const normalizedName = file.filename.replace(/\\/g, '/')
    const parts = normalizedName.split('/')

    // Detect URL (URLs should not be parsed as folder hierarchy)
    const isUrl = file.filename.startsWith('http://') || file.filename.startsWith('https://')

    if (isUrl || parts.length === 1) {
      // Root item
      // Check if it's an explicit folder that should merge with an existing implicit one?
      if (item.is_folder) {
        const existingIndex = roots.findIndex((n) => n.is_folder && n.filename === item.filename)
        if (existingIndex !== -1) {
          const existing = roots[existingIndex]
          // Merge children from implicit to explicit
          if (existing.children && existing.children.length > 0) {
            item.children = [...(item.children || []), ...existing.children]
          }
          // Replace implicit with explicit
          roots[existingIndex] = item
        } else {
          roots.push(item)
        }
      } else {
        roots.push(item)
      }
    } else {
      // Path based logic for files like "A/B.txt"
      let currentLevel = roots
      let currentPath = ''

      for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i]
        currentPath = currentPath ? `${currentPath}/${part}` : part

        // Find existing node in currentLevel
        let node = currentLevel.find((n) => n.filename === part && n.is_folder)

        if (!node) {
          node = {
            file_id: `folder-${currentPath}`,
            filename: part,
            displayName: part,
            is_folder: true,
            children: [],
            created_at: file.created_at,
            status: 'done'
          }
          currentLevel.push(node)
        }
        currentLevel = node.children
      }

      const fileName = parts[parts.length - 1]
      item.displayName = fileName
      currentLevel.push(item)
    }
  })

  // Sort: folders first, then files, by name
  const sortNodes = (nodes) => {
    nodes.sort((a, b) => {
      if (a.is_folder && !b.is_folder) return -1
      if (!a.is_folder && b.is_folder) return 1

      if (sortField.value === 'filename') {
        return (a.filename || '').localeCompare(b.filename || '')
      } else if (sortField.value === 'created_at') {
        return new Date(b.created_at || 0) - new Date(a.created_at || 0)
      } else if (sortField.value === 'status') {
        const statusOrder = {
          done: 1,
          indexed: 1,
          processing: 2,
          indexing: 2,
          parsing: 2,
          waiting: 3,
          uploaded: 3,
          parsed: 3,
          failed: 4,
          error_indexing: 4,
          error_parsing: 4
        }
        return (statusOrder[a.status] || 5) - (statusOrder[b.status] || 5)
      }
      return 0
    })
    nodes.forEach((node) => {
      if (node.children) sortNodes(node.children)
    })
  }

  sortNodes(roots)
  return roots
}

// Filtered file list
const filteredFiles = computed(() => {
  let filtered = files.value
  const nameFilter = filenameFilter.value.trim().toLowerCase()
  const status = statusFilter.value

  // Apply filters
  if (nameFilter || status !== 'all') {
    // Use flat list in search/filter mode
    return files.value
      .filter((file) => {
        const nameMatch =
          !nameFilter || (file.filename && file.filename.toLowerCase().includes(nameFilter))
        const statusMatch =
          status === 'all' ||
          file.status === status ||
          (status === 'indexed' && file.status === 'done') ||
          (status === 'error_indexing' && file.status === 'failed')
        return nameMatch && statusMatch
      })
      .map((f) => ({ ...f, displayName: f.filename }))
  }

  return buildFileTree(filtered)
})

// Empty state text
const emptyText = computed(() => {
  return filenameFilter.value
    ? `No files found containing "${filenameFilter.value}"`
    : 'No files'
})

// Determine whether batch delete is available
const canBatchDelete = computed(() => {
  return selectedRowKeys.value.some((key) => {
    const file = files.value.find((f) => f.file_id === key)
    return file && !(lock.value || file.status === 'processing' || file.status === 'waiting')
  })
})

// Determine whether batch parse is available
const canBatchParse = computed(() => {
  return selectedRowKeys.value.some((key) => {
    const file = filteredFiles.value.find((f) => f.file_id === key)
    return file && !lock.value && (file.status === 'uploaded' || file.status === 'error_parsing')
  })
})

// Determine whether batch index is available
const canBatchIndex = computed(() => {
  return selectedRowKeys.value.some((key) => {
    const file = filteredFiles.value.find((f) => f.file_id === key)
    return (
      file &&
      !lock.value &&
      (file.status === 'parsed' ||
        file.status === 'error_indexing' ||
        (!isLightRAG.value && (file.status === 'done' || file.status === 'indexed')))
    )
  })
})

const showAddFilesModal = (options = {}) => {
  emit('showAddFilesModal', options)
}

const handleRefresh = () => {
  // Reset to first page on refresh
  paginationConfig.value.current = 1
  store.getDatabaseInfo(undefined, true) // Skip query params for manual refresh
}

const toggleRightPanel = () => {
  console.log(props.rightPanelVisible)
  emit('toggleRightPanel')
}

const onSelectChange = (keys, selectedRows) => {
  // Keep only non-folder file IDs
  const fileKeys = selectedRows.filter((row) => !row.is_folder).map((row) => row.file_id)

  selectedRowKeys.value = fileKeys
}

const getCheckboxProps = (record) => ({
  disabled:
    lock.value || record.status === 'processing' || record.status === 'waiting' || record.is_folder
})

const onFilterChange = (e) => {
  filenameFilter.value = e.target.value
  // Reset to first page when filters change
  paginationConfig.value.current = 1
}

const handleDeleteFile = (fileId) => {
  store.handleDeleteFile(fileId)
  closePopover(fileId)
}

const handleDeleteFolder = (record) => {
  closePopover(record.file_id)
  Modal.confirm({
    title: 'Delete Folder',
    content: `Are you sure you want to delete folder "${record.filename}" and all its contents?`,
    okText: 'Confirm',
    cancelText: 'Cancel',
    onOk: async () => {
      try {
        await store.deleteFile(record.file_id)
        message.success('Deleted successfully')
      } catch {
        // Error handled in store but we can add extra handling if needed
      }
    }
  })
}

const handleBatchDelete = () => {
  store.handleBatchDelete()
}

const handleBatchParse = async () => {
  const validKeys = selectedRowKeys.value.filter((key) => {
    const file = files.value.find((f) => f.file_id === key)
    return file && (file.status === 'uploaded' || file.status === 'error_parsing')
  })

  if (validKeys.length === 0) {
    message.warning('No parsable files selected')
    return
  }

  await store.parseFiles(validKeys)
  selectedRowKeys.value = []
}

const handleBatchIndex = async () => {
  const validKeys = selectedRowKeys.value.filter((key) => {
    const file = files.value.find((f) => f.file_id === key)
    return (
      file &&
      (file.status === 'parsed' ||
        file.status === 'error_indexing' ||
        (!isLightRAG.value && (file.status === 'done' || file.status === 'indexed')))
    )
  })

  if (validKeys.length === 0) {
    message.warning('No indexable files selected')
    return
  }

  currentIndexFileIds.value = [...validKeys]
  isBatchIndexOperation.value = true
  indexConfigModalTitle.value = 'Batch Index Parameters'
  indexConfigModalVisible.value = true
}

const openFileDetail = (record) => {
  console.log('openFileDetail', record)
  store.openFileDetail(record)
}

const handleDownloadFile = async (record) => {
  closePopover(record.file_id)
  const dbId = store.databaseId
  if (!dbId) {
    console.error('Failed to get database ID, databaseId:', store.databaseId, 'record:', record)
    message.error('Failed to get database ID, please refresh and try again')
    return
  }

  console.log('Start downloading file:', { dbId, fileId: record.file_id, record })

  try {
    const response = await documentApi.downloadDocument(dbId, record.file_id)

    // Extract filename
    const contentDisposition = response.headers.get('content-disposition')
    let filename = record.filename
    if (contentDisposition) {
      // Try RFC 2231 format filename*=UTF-8''... first
      const rfc2231Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/)
      if (rfc2231Match) {
        try {
          filename = decodeURIComponent(rfc2231Match[1])
        } catch (error) {
          console.warn('Failed to decode RFC2231 filename:', rfc2231Match[1], error)
        }
      } else {
        // Fallback to standard filename="..." format
        const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1].replace(/['"]/g, '')
          // Decode URL-encoded filename
          try {
            filename = decodeURIComponent(filename)
          } catch (error) {
            console.warn('Failed to decode filename:', filename, error)
            // If decoding fails, use original filename
          }
        }
      }
    }

    // Create blob and download
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Error while downloading file:', error)
    const errorMessage = error.message || 'Download failed, please try again later'
    message.error(errorMessage)
  }
}

const handleParseFile = async (record) => {
  closePopover(record.file_id)
  await store.parseFiles([record.file_id])
}

const defaultIndexParams = {
  chunk_size: 1000,
  chunk_overlap: 200,
  qa_separator: '',
  chunk_preset_id: ''
}

const loadRecordProcessingParams = async (record) => {
  if (record?.processing_params) {
    return record.processing_params
  }

  const detail = await documentApi.getDocumentInfo(store.databaseId, record.file_id)
  return detail?.processing_params || null
}

const handleIndexFile = async (record) => {
  closePopover(record.file_id)
  currentIndexFileIds.value = [record.file_id]
  isBatchIndexOperation.value = false
  indexConfigModalTitle.value = 'Index Parameters'

  Object.assign(indexParams.value, defaultIndexParams)
  const processingParams = await loadRecordProcessingParams(record)
  if (processingParams) {
    Object.assign(indexParams.value, processingParams)
  }

  indexConfigModalVisible.value = true
}

const handleReindexFile = async (record) => {
  closePopover(record.file_id)
  currentIndexFileIds.value = [record.file_id]
  isBatchIndexOperation.value = false
  indexConfigModalTitle.value = 'Reindex Parameters'

  Object.assign(indexParams.value, defaultIndexParams)
  const processingParams = await loadRecordProcessingParams(record)
  if (processingParams) {
    Object.assign(indexParams.value, processingParams)
  }

  indexConfigModalVisible.value = true
}

// Confirm indexing (shared for index and reindex)
const handleIndexConfigConfirm = async () => {
  try {
    // Call indexFiles API (supports params)
    const result = await store.indexFiles(currentIndexFileIds.value, buildIndexParamsPayload())
    if (result) {
      currentIndexFileIds.value = []
      // Clear selection
      if (isBatchIndexOperation.value) {
        selectedRowKeys.value = []
      }
      // Close modal
      indexConfigModalVisible.value = false

      // Reset parameters to defaults
      Object.assign(indexParams.value, {
        chunk_size: 1000,
        chunk_overlap: 200,
        qa_separator: '',
        chunk_preset_id: ''
      })
    } else {
      // message.error(`Index failed: ${result.message}`); // store already shows message
    }
  } catch (error) {
    console.error('Indexing failed:', error)
    const errorMessage = error.message || 'Indexing failed, please try again later'
    message.error(errorMessage)
  }
}

// Cancel indexing
const handleIndexConfigCancel = () => {
  indexConfigModalVisible.value = false
  currentIndexFileIds.value = []
  isBatchIndexOperation.value = false
  // Reset parameters to defaults
  Object.assign(indexParams.value, defaultIndexParams)
}

// Import utility functions
import { getFileIcon, getFileIconColor, formatRelativeTime } from '@/utils/file_utils'
import ChunkParamsConfig from '@/components/ChunkParamsConfig.vue'
</script>

<style scoped>
.file-table-container {
  display: flex;
  flex-grow: 1;
  flex-direction: column;
  max-height: 100%;
  background: var(--gray-10);
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid var(--gray-150);
  /* padding-top: 6px; */
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  padding: 8px 8px;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 6px;

  .action-searcher {
    width: 120px;
    margin-right: 8px;
    border-radius: 6px;
    padding: 4px 8px;
    border: none;
    box-shadow: 0 0 0 1px var(--shadow-1);
  }
}

.batch-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  background-color: var(--main-10);
  border-radius: 4px;
  margin-bottom: 4px;
  flex-shrink: 0;
}

.batch-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-info span {
  font-size: 12px;
  font-weight: 500;
  color: var(--gray-700);
}

.batch-actions .ant-btn {
  font-size: 12px;
  padding: 4px 8px;
  height: auto;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 4px;

  svg {
    width: 14px;
    height: 14px;
  }
}

.my-table {
  flex: 1;
  overflow: auto;
  background-color: transparent;
  min-height: 0;
  table-layout: fixed;
  padding-left: 4px;
}

.my-table .main-btn {
  padding: 0;
  height: auto;
  line-height: 1.4;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  text-decoration: none;
}

.my-table .main-btn:hover {
  cursor: pointer;
  color: var(--main-color);
}

.my-table .del-btn {
  color: var(--gray-500);
}

.my-table .download-btn {
  color: var(--gray-500);
}

.my-table .download-btn:hover {
  color: var(--main-color);
}

.my-table .rechunk-btn {
  color: var(--gray-500);
}

/* Keep consistent icon size for table action buttons */
.my-table .table-row-actions {
  display: flex;
}

.my-table .table-row-actions button {
  display: flex;
  align-items: center;
}

.my-table .table-row-actions button svg {
  width: 16px;
  height: 16px;
}

.my-table .rechunk-btn:hover {
  color: var(--color-warning-500);
}

.my-table .del-btn:hover {
  color: var(--color-error-500);
}

.my-table .del-btn:disabled {
  cursor: not-allowed;
}

.my-table .span-type {
  display: inline-block;
  padding: 1px 5px;
  font-size: 10px;
  font-weight: bold;
  color: var(--gray-0);
  border-radius: 4px;
  text-transform: uppercase;
  opacity: 0.9;
}

.my-table .span-type.md,
.my-table .span-type.markdown {
  background-color: var(--gray-200);
  color: var(--gray-800);
}

.auto-refresh-btn {
  height: 24px;
  padding: 0 8px;
  font-size: 12px;
}

.panel-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  padding: 4px;
  color: var(--gray-600);
  transition: all 0.1s ease;
  font-size: 12px;
  width: auto;
  height: auto;

  &.expand {
    transform: scaleX(-1);
  }

  &.expanded {
    transform: scaleX(1);
  }
}

.panel-action-btn.auto-refresh-btn.ant-btn-primary {
  background-color: var(--main-color);
  border-color: var(--main-color);
  color: var(--gray-0);
}

.panel-action-btn:hover {
  background-color: var(--gray-50);
  color: var(--main-color);
  /* border: 1px solid var(--main-100); */
}

.panel-action-btn.active {
  color: var(--main-color);
  background-color: var(--gray-100);
  font-weight: 600;
  box-shadow: 0 0 0 1px var(--shadow-1);
}

.action-trigger-btn {
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: var(--gray-500);
  transition: all 0.2s;

  &:hover {
    background-color: var(--gray-100);
    color: var(--main-color);
  }

  svg {
    width: 16px;
    height: 16px;
  }
}

/* Table row selection styling */
:deep(.ant-table-tbody > tr.ant-table-row-selected > td) {
  background-color: var(--main-5);
}

:deep(.ant-table-tbody > tr.ant-table-row-selected.ant-table-row:hover > td) {
  background-color: var(--main-20);
}

:deep(.ant-table-tbody > tr:hover > td) {
  background-color: var(--main-5);
}

.folder-row {
  display: flex;
  align-items: center;
  cursor: pointer;

  &:hover {
    color: var(--main-color);
  }
}

:deep(.drop-over-folder) {
  background-color: var(--primary-50) !important;
  outline: 2px dashed var(--main-color);
  outline-offset: -2px;
  z-index: 10;

  td {
    background-color: transparent !important;
  }
}

.upload-btn-group {
  display: flex;
  align-items: center;
  gap: 8px;

  .upload-btn {
    height: 28px;
    font-size: 13px;
    display: flex;
    padding: 0 12px;
    align-items: center;
    justify-content: center;
    gap: 4px;
  }
}
</style>

<style lang="less">
.file-action-popover {
  .ant-popover-inner {
    padding: 4px;
  }

  .ant-popover-inner {
    border-radius: 8px;
    border: 1px solid var(--gray-150);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    overflow: hidden;
  }

  .ant-popover-arrow {
    display: none;
  }
}

.file-action-list {
  display: flex;
  flex-direction: column;
  gap: 2px;

  .ant-btn {
    text-align: left;
    height: 30px;
    font-size: 14px;
    display: flex;
    align-items: center;
    border-radius: 6px;
    padding: 0 8px;
    border: none;
    box-shadow: none;

    &:hover {
      background-color: var(--gray-50);
      color: var(--main-color);
    }

    &.ant-btn-dangerous:hover {
      background-color: var(--color-error-50);
      color: var(--color-error-500);
    }

    .anticon,
    .lucide {
      margin-right: 10px;
    }

    span {
      font-size: 13px;
    }
  }

  .ant-btn:disabled {
    background-color: transparent;
    color: var(--gray-300);
    cursor: not-allowed;
  }
}

.file-info-popover {
  .ant-popover-inner {
    border-radius: 8px;
  }

  // .ant-popover-inner-content {
  //   padding: 16px;
  // }

  .file-info-card {
    min-width: 120px;
    max-width: 320px;
    font-size: 13px;

    .info-row {
      display: flex;
      margin-bottom: 8px;
      line-height: 1.5;
      align-items: flex-start;

      &:last-child {
        margin-bottom: 0;
      }

      .label {
        color: var(--gray-500);
        width: 40px;
        flex-shrink: 0;
        text-align: right;
        margin-right: 12px;
        font-weight: 500;
      }

      .value {
        color: var(--gray-900);
        word-break: break-all;
        flex: 1;
        font-family: monospace; /* Optional: for ID and numbers */
      }

      &.error {
        .label {
          color: var(--color-error-500);
        }
        .value {
          color: var(--color-error-500);
        }
      }
    }
  }
}
</style>
