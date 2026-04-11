import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { databaseApi, documentApi, queryApi } from '@/apis/knowledge_api'
import { useTaskerStore } from '@/stores/tasker'
import { useUserStore } from '@/stores/user'
import { useRouter } from 'vue-router'
import { parseToShanghai } from '@/utils/time'

export const useDatabaseStore = defineStore('database', () => {
  const router = useRouter()
  const taskerStore = useTaskerStore()
  const userStore = useUserStore()

  // State
  const databases = ref([])
  const database = ref({})
  const databaseId = ref(null)
  const selectedFile = ref(null)

  const queryParams = ref([])
  const meta = reactive({})
  const selectedRowKeys = ref([])

  const state = reactive({
    listLoading: false,
    creating: false,
    databaseLoading: false,
    refrashing: false,
    searchLoading: false,
    lock: false,
    fileDetailModalVisible: false,
    fileDetailLoading: false,
    batchDeleting: false,
    chunkLoading: false,
    autoRefresh: false,
    queryParamsLoading: false,
    rightPanelVisible: true
  })

  let refreshInterval = null
  let autoRefreshSource = null // Tracks whether auto-refresh was user-triggered or automatic
  let autoRefreshManualOverride = false // Indicates the user explicitly disabled auto-refresh

  // Actions
  // Admins get all knowledge bases; regular users get only those they can access
  async function loadDatabases() {
    state.listLoading = true
    try {
      const data = userStore.isAdmin
        ? await databaseApi.getDatabases()
        : await databaseApi.getAccessibleDatabases()
      const list = data?.databases || []
      databases.value = list.sort((a, b) => {
        const timeA = parseToShanghai(a.created_at)
        const timeB = parseToShanghai(b.created_at)
        if (!timeA && !timeB) return 0
        if (!timeA) return 1
        if (!timeB) return -1
        return timeB.valueOf() - timeA.valueOf() // Sort in descending order, newest first
      })
    } catch (error) {
      console.error('Failed to load database list:', error)
      if (error.message.includes('permission')) {
        message.error('No permission to access knowledge base')
      }
      throw error
    } finally {
      state.listLoading = false
    }
  }

  async function createDatabase(formData) {
    // Validation
    if (!formData.database_name?.trim()) {
      message.error('Database name cannot be empty')
      return false
    }

    if (!formData.kb_type) {
      message.error('Please select a knowledge base type')
      return false
    }

    // Reranker model validation for vector databases
    if (['milvus'].includes(formData.kb_type)) {
      if (formData.reranker_config?.enabled && !formData.reranker_config?.model) {
        message.error('Please select a reranker model')
        return false
      }
    }

    state.creating = true
    try {
      const data = await databaseApi.createDatabase(formData)
      message.success('Created successfully')
      await loadDatabases() // Refresh list
      return data
    } catch (error) {
      console.error('Failed to create database:', error)
      message.error(error.message || 'Failed to create')
      throw error
    } finally {
      state.creating = false
    }
  }

  async function getDatabaseInfo(id, skipQueryParams = false, isBackground = false) {
    const db_id = id || databaseId.value
    if (!db_id) return

    if (!isBackground) {
      state.lock = true
      state.databaseLoading = true
    }
    try {
      const data = await databaseApi.getDatabaseInfo(db_id)
      database.value = data
      ensureAutoRefreshForProcessing(data?.files)

      // Only load query parameters if explicitly requested or if they have not been loaded yet
      if (!skipQueryParams && queryParams.value.length === 0) {
        await loadQueryParams(db_id)
      }
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Failed to get database information')
    } finally {
      if (!isBackground) {
        state.lock = false
        state.databaseLoading = false
      }
    }
  }

  async function updateDatabaseInfo(formData) {
    try {
      state.lock = true
      await databaseApi.updateDatabase(databaseId.value, formData)
      message.success('Knowledge base information updated successfully')
      await getDatabaseInfo() // Load query params after updating database info
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Update failed')
    } finally {
      state.lock = false
    }
  }

  function deleteDatabase() {
    Modal.confirm({
      title: 'Delete Database',
      content: 'Are you sure you want to delete this database?',
      okText: 'Confirm',
      cancelText: 'Cancel',
      onOk: async () => {
        state.lock = true
        try {
          const data = await databaseApi.deleteDatabase(databaseId.value)
          message.success(data.message || 'Deleted successfully')
          router.push('/database')
        } catch (error) {
          console.error(error)
          message.error(error.message || 'Deletion failed')
        } finally {
          state.lock = false
        }
      }
    })
  }

  async function deleteFile(fileId) {
    state.lock = true
    try {
      await documentApi.deleteDocument(databaseId.value, fileId)
      await getDatabaseInfo(undefined, true) // Skip query params for file deletion
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Deletion failed')
      throw error
    } finally {
      state.lock = false
    }
  }

  function handleDeleteFile(fileId) {
    Modal.confirm({
      title: 'Delete File',
      content: 'Are you sure you want to delete this file?',
      okText: 'Confirm',
      cancelText: 'Cancel',
      onOk: () => deleteFile(fileId)
    })
  }

  function handleBatchDelete() {
    const files = database.value.files || {}
    const validFileIds = selectedRowKeys.value.filter((fileId) => {
      const file = files[fileId]
      return file && !(file.status === 'processing' || file.status === 'waiting')
    })

    if (validFileIds.length === 0) {
      message.info('No files available for deletion')
      return
    }

    Modal.confirm({
      title: 'Batch Delete Files',
      content: `Are you sure you want to delete the selected ${validFileIds.length} files?`,
      okText: 'Confirm',
      cancelText: 'Cancel',
      onOk: async () => {
        state.batchDeleting = true
        let successCount = 0
        let failureCount = 0
        let processedCount = 0
        const totalCount = validFileIds.length
        const progressKey = `batch-delete-${Date.now()}`
        message.loading({ content: `Deleting files 0/${totalCount}`, key: progressKey, duration: 0 })

        try {
          const CHUNK_SIZE = 50
          for (let i = 0; i < totalCount; i += CHUNK_SIZE) {
            const chunk = validFileIds.slice(i, i + CHUNK_SIZE)

            try {
              const res = await documentApi.batchDeleteDocuments(databaseId.value, chunk)
              successCount += res.deleted_count || 0
              if (res.failed_items) {
                failureCount += res.failed_items.length
              }
            } catch (err) {
              console.error(`Batch ${i / CHUNK_SIZE + 1} failed:`, err)
              failureCount += chunk.length
            } finally {
              processedCount += chunk.length
              message.loading({
                content: `Deleting files ${processedCount}/${totalCount}`,
                key: progressKey,
                duration: 0
              })
            }
          }

          message.destroy(progressKey)
          if (successCount > 0 && failureCount === 0) {
            message.success(`Successfully deleted ${successCount} files`)
          } else if (successCount > 0 && failureCount > 0) {
            message.warning(`Successfully deleted ${successCount} files, ${failureCount} files failed to delete`)
          } else if (failureCount > 0) {
            message.error(`${failureCount} files failed to delete`)
          }

          selectedRowKeys.value = []
          await getDatabaseInfo(undefined, true) // Skip query params for batch deletion
        } catch (error) {
          message.destroy(progressKey)
          console.error('Batch delete error:', error)
          message.error(error.message || 'An error occurred during batch deletion process')
        } finally {
          state.batchDeleting = false
        }
      }
    })
  }

  const processingStatuses = new Set(['processing', 'waiting', 'parsing', 'indexing'])

  function enableAutoRefresh(source = 'auto') {
    if (autoRefreshManualOverride && source === 'auto') {
      return
    }

    if (!state.autoRefresh) {
      state.autoRefresh = true
      autoRefreshSource = source
      autoRefreshManualOverride = false
      startAutoRefresh()
      return
    }

    if (source === 'auto' && autoRefreshSource !== 'manual') {
      autoRefreshSource = 'auto'
    }
  }

  function ensureAutoRefreshForProcessing(filesMap) {
    const files = Object.values(filesMap || {})
    const hasPending = files.some((file) => file && processingStatuses.has(file.status))
    if (hasPending) {
      enableAutoRefresh('auto')
    } else if (autoRefreshSource === 'auto' && state.autoRefresh) {
      state.autoRefresh = false
      autoRefreshSource = null
      autoRefreshManualOverride = false
      stopAutoRefresh()
    }
    return hasPending
  }

  async function moveFile(fileId, newParentId) {
    state.lock = true
    try {
      await documentApi.moveDocument(databaseId.value, fileId, newParentId)
      await getDatabaseInfo(undefined, true) // Skip query params for file movement
      message.success('Moved successfully')
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Move failed')
      throw error
    } finally {
      state.lock = false
    }
  }

  async function addFiles({ items, contentType, params, parentId }) {
    if (items.length === 0) {
      message.error(contentType === 'file' ? 'Please upload a file first' : 'Please enter a valid web link')
      return
    }

    state.chunkLoading = true
    try {
      const requestParams = { ...params, content_type: contentType }
      if (parentId) {
        requestParams.parent_id = parentId
      }
      const data = await documentApi.addDocuments(databaseId.value, items, requestParams)
      if (data.status === 'success' || data.status === 'queued') {
        const itemType = contentType === 'file' ? 'File' : 'URL'
        enableAutoRefresh('auto')
        message.success(data.message || `${itemType} has been submitted for processing, please check the progress in the Task Center`)
        if (data.task_id) {
          taskerStore.registerQueuedTask({
            task_id: data.task_id,
            name: `Knowledge base import (${databaseId.value || ''})`,
            task_type: 'knowledge_ingest',
            message: data.message,
            payload: {
              db_id: databaseId.value,
              count: items.length,
              content_type: contentType
            }
          })
        }
        await delayedRefresh() // Refresh after delay
        return true // Indicate success
      } else {
        message.error(data.message || 'Processing failed')
        return false
      }
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Request processing failed')
      return false
    } finally {
      state.chunkLoading = false
    }
  }

  async function parseFiles(fileIds) {
    if (fileIds.length === 0) return
    state.chunkLoading = true
    try {
      const data = await documentApi.parseDocuments(databaseId.value, fileIds)
      if (data.status === 'success' || data.status === 'queued') {
        enableAutoRefresh('auto')
        message.success(data.message || 'Parsing task submitted')
        if (data.task_id) {
          taskerStore.registerQueuedTask({
            task_id: data.task_id,
            name: `Document parsing (${databaseId.value})`,
            task_type: 'knowledge_parse',
            message: data.message,
            payload: { db_id: databaseId.value, count: fileIds.length }
          })
        }
        await delayedRefresh() // Refresh after 1 second delay
        return true
      } else {
        message.error(data.message || 'Submission failed')
        return false
      }
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Request failed')
      return false
    } finally {
      state.chunkLoading = false
    }
  }

  async function indexFiles(fileIds, params = {}) {
    if (fileIds.length === 0) return
    state.chunkLoading = true
    try {
      const data = await documentApi.indexDocuments(databaseId.value, fileIds, params)
      if (data.status === 'success' || data.status === 'queued') {
        enableAutoRefresh('auto')
        message.success(data.message || 'Indexing task submitted')
        if (data.task_id) {
          taskerStore.registerQueuedTask({
            task_id: data.task_id,
            name: `Document indexing (${databaseId.value})`,
            task_type: 'knowledge_index',
            message: data.message,
            payload: { db_id: databaseId.value, count: fileIds.length }
          })
        }
        await delayedRefresh() // Refresh after 1 second delay
        return true
      } else {
        message.error(data.message || 'Submission failed')
        return false
      }
    } catch (error) {
      console.error(error)
      message.error(error.message || 'Request failed')
      return false
    } finally {
      state.chunkLoading = false
    }
  }

  async function openFileDetail(record) {
    // As long as there is a markdown_file (implied in status >= parsed) or error_indexing (meaning parsing succeeded but indexing failed), it can be viewed
    const allowStatuses = ['done', 'parsed', 'indexed', 'error_indexing']
    if (!allowStatuses.includes(record.status)) {
      message.error('File processing not complete, please try again later')
      return
    }
    state.fileDetailModalVisible = true
    selectedFile.value = { ...record, lines: [] }
    state.fileDetailLoading = true
    state.lock = true

    try {
      const data = await documentApi.getDocumentInfo(databaseId.value, record.file_id)
      if (data.status == 'failed') {
        message.error(data.message)
        state.fileDetailModalVisible = false
        return
      }
      selectedFile.value = { ...record, lines: data.lines || [], content: data.content }
    } catch (error) {
      console.error(error)
      message.error(error.message)
      state.fileDetailModalVisible = false
    } finally {
      state.fileDetailLoading = false
      state.lock = false
    }
  }

  async function loadQueryParams(id) {
    const db_id = id || databaseId.value
    if (!db_id) return

    state.queryParamsLoading = true
    try {
      const response = await queryApi.getKnowledgeBaseQueryParams(db_id)
      queryParams.value = response.params?.options || []

      // Create a set of currently supported parameter keys
      const supportedParamKeys = new Set(queryParams.value.map((param) => param.key))

      // Remove unsupported parameters from meta
      for (const key in meta) {
        if (key !== 'db_id' && !supportedParamKeys.has(key)) {
          delete meta[key]
        }
      }

      // Add default values for supported parameters that are not in meta
      queryParams.value.forEach((param) => {
        if (!(param.key in meta)) {
          meta[param.key] = param.default
        }
      })
    } catch (error) {
      console.error('Failed to load query params:', error)
      message.error('Failed to load query parameters')
    } finally {
      state.queryParamsLoading = false
    }
  }

  function startAutoRefresh() {
    if (state.autoRefresh && !refreshInterval) {
      refreshInterval = setInterval(() => {
        getDatabaseInfo(undefined, true, true) // Skip loading query params during auto-refresh
      }, 1000)
    }
  }

  function stopAutoRefresh() {
    if (refreshInterval) {
      clearInterval(refreshInterval)
      refreshInterval = null
    }
  }

  // Delayed document refresh (refresh after 1 second delay)
  async function delayedRefresh() {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    await getDatabaseInfo(undefined, true)
  }

  function toggleAutoRefresh() {
    const nextState = !state.autoRefresh
    state.autoRefresh = nextState
    if (nextState) {
      autoRefreshSource = 'manual'
      autoRefreshManualOverride = false
      startAutoRefresh()
    } else {
      autoRefreshManualOverride = true
      autoRefreshSource = null
      stopAutoRefresh()
    }
  }

  function selectAllFailedFiles() {
    const files = Object.values(database.value.files || {})
    const failedFiles = files.filter((file) => file.status === 'failed').map((file) => file.file_id)

    const newSelectedKeys = [...new Set([...selectedRowKeys.value, ...failedFiles])]
    selectedRowKeys.value = newSelectedKeys

    if (failedFiles.length > 0) {
      message.success(`Selected ${failedFiles.length} failed files`)
    } else {
      message.info('No failed files currently')
    }
  }

  return {
    databases,
    database,
    databaseId,
    selectedFile,
    queryParams,
    meta,
    selectedRowKeys,
    state,
    loadDatabases,
    createDatabase,
    getDatabaseInfo,
    updateDatabaseInfo,
    deleteDatabase,
    deleteFile,
    handleDeleteFile,
    handleBatchDelete,
    moveFile,
    addFiles,
    parseFiles,
    indexFiles,
    openFileDetail,
    loadQueryParams,

    startAutoRefresh,
    stopAutoRefresh,
    toggleAutoRefresh,
    selectAllFailedFiles
  }
})
