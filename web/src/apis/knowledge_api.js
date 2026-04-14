import { apiGet, apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete, apiRequest } from './base'

/**
 * Knowledge base management API module
 * Includes database management, document management, query endpoints, and related features
 */

// =============================================================================
// === Database management group ===
// =============================================================================

export const databaseApi = {
  /**
   * Get all knowledge bases
   * @returns {Promise} - Knowledge base list
   */
  getDatabases: async () => {
    return apiAdminGet('/api/knowledge/databases')
  },

  /**
   * Create a knowledge base
   * @param {Object} databaseData - Knowledge base data
   * @returns {Promise} - Creation result
   */
  createDatabase: async (databaseData) => {
    return apiAdminPost('/api/knowledge/databases', databaseData)
  },

  /**
   * Get knowledge base details
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Knowledge base details
   */
  getDatabaseInfo: async (dbId) => {
    return apiAdminGet(`/api/knowledge/databases/${dbId}`)
  },

  /**
   * Update knowledge base information
   * @param {string} dbId - Knowledge base ID
   * @param {Object} updateData - Update data
   * @returns {Promise} - Update result
   */
  updateDatabase: async (dbId, updateData) => {
    return apiAdminPut(`/api/knowledge/databases/${dbId}`, updateData)
  },

  /**
   * Delete a knowledge base
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Deletion result
   */
  deleteDatabase: async (dbId) => {
    return apiAdminDelete(`/api/knowledge/databases/${dbId}`)
  },

  /**
   * Use AI to generate or refine the knowledge base description
   * @param {string} name - Knowledge base name
   * @param {string} currentDescription - Current description (optional)
   * @param {Array} fileList - File list (optional)
   * @returns {Promise} - Generated result
   */
  generateDescription: async (name, currentDescription = '', fileList = []) => {
    return apiAdminPost('/api/knowledge/generate-description', {
      name,
      current_description: currentDescription,
      file_list: fileList
    })
  },

  /**
   * Get the list of knowledge bases the current user can access (for agent configuration)
   * @returns {Promise} - Accessible knowledge bases
   */
  getAccessibleDatabases: async () => {
    return apiGet('/api/knowledge/databases/accessible')
  }
}

// =============================================================================
// === Document management group ===
// =============================================================================

export const documentApi = {
  /**
   * Create a folder
   * @param {string} dbId - Knowledge base ID
   * @param {string} folderName - Folder name
   * @param {string} parentId - Parent folder ID
   * @returns {Promise} - Creation result
   */
  createFolder: async (dbId, folderName, parentId = null) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/folders`, {
      folder_name: folderName,
      parent_id: parentId
    })
  },

  /**
   * Move a document or folder
   * @param {string} dbId - Knowledge base ID
   * @param {string} docId - Document or folder ID
   * @param {string} newParentId - New parent folder ID
   * @returns {Promise} - Move result
   */
  moveDocument: async (dbId, docId, newParentId) => {
    return apiAdminPut(`/api/knowledge/databases/${dbId}/documents/${docId}/move`, {
      new_parent_id: newParentId
    })
  },

  /**
   * Add documents to a knowledge base
   * @param {string} dbId - Knowledge base ID
   * @param {Array} items - Document list
   * @param {Object} params - Processing parameters
   * @returns {Promise} - Add result
   */
  addDocuments: async (dbId, items, params = {}) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/documents`, {
      items,
      params
    })
  },

  /**
   * Ingest structured academic dataset (JSON/CSV) directly to graph storage.
   * @param {string} dbId - Knowledge base ID
   * @param {Object} payload - Structured payload (triples, records/data, csv_text)
   * @returns {Promise} - Queued task result
   */
  ingestScivalDataset: async (dbId, payload) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/scival-ingest`, payload)
  },

  /**
   * Get document details
   * @param {string} dbId - Knowledge base ID
   * @param {string} docId - Document ID
   * @returns {Promise} - Document details
   */
  getDocumentInfo: async (dbId, docId) => {
    return apiAdminGet(`/api/knowledge/databases/${dbId}/documents/${docId}`)
  },

  /**
   * Delete a document
   * @param {string} dbId - Knowledge base ID
   * @param {string} docId - Document ID
   * @returns {Promise} - Deletion result
   */
  deleteDocument: async (dbId, docId) => {
    return apiAdminDelete(`/api/knowledge/databases/${dbId}/documents/${docId}`)
  },

  /**
   * Delete documents in batch
   * @param {string} dbId - Knowledge base ID
   * @param {Array} fileIds - File ID list
   * @returns {Promise} - Batch deletion result
   */
  batchDeleteDocuments: async (dbId, fileIds) => {
    return apiRequest(
      `/api/knowledge/databases/${dbId}/documents/batch`,
      {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(fileIds)
      },
      true,
      'json'
    )
  },

  /**
   * Download a document
   * @param {string} dbId - Knowledge base ID
   * @param {string} docId - Document ID
   * @returns {Promise} - Response object
   */
  downloadDocument: async (dbId, docId) => {
    return apiAdminGet(`/api/knowledge/databases/${dbId}/documents/${docId}/download`, {}, 'blob')
  },

  /**
   * Manually trigger document parsing
   * @param {string} dbId - Knowledge base ID
   * @param {Array} fileIds - File ID list
   * @returns {Promise} - Parsing task result
   */
  parseDocuments: async (dbId, fileIds) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/documents/parse`, fileIds)
  },

  /**
   * Manually trigger document indexing
   * @param {string} dbId - Knowledge base ID
   * @param {Array} fileIds - File ID list
   * @param {Object} params - Processing parameters
   * @returns {Promise} - Indexing task result
   */
  indexDocuments: async (dbId, fileIds, params = {}) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/documents/index`, {
      file_ids: fileIds,
      params
    })
  }
}

// =============================================================================
// === Query group ===
// =============================================================================

export const queryApi = {
  /**
   * Query a knowledge base
   * @param {string} dbId - Knowledge base ID
   * @param {string} query - Query text
   * @param {Object} meta - Query parameters
   * @returns {Promise} - Query result
   */
  queryKnowledgeBase: async (dbId, query, meta = {}) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/query`, {
      query,
      meta
    })
  },

  /**
   * Test a knowledge base query
   * @param {string} dbId - Knowledge base ID
   * @param {string} query - Query text
   * @param {Object} meta - Query parameters
   * @returns {Promise} - Test result
   */
  queryTest: async (dbId, query, meta = {}) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/query-test`, {
      query,
      meta
    })
  },

  /**
   * Get knowledge base query parameters
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Query parameters
   */
  getKnowledgeBaseQueryParams: async (dbId) => {
    return apiAdminGet(`/api/knowledge/databases/${dbId}/query-params`)
  },

  /**
   * Update knowledge base query parameters
   * @param {string} dbId - Knowledge base ID
   * @param {Object} params - Query parameters
   * @returns {Promise} - Update result
   */
  updateKnowledgeBaseQueryParams: async (dbId, params) => {
    return apiAdminPut(`/api/knowledge/databases/${dbId}/query-params`, params)
  },

  /**
   * Generate test questions for a knowledge base
   * @param {string} dbId - Knowledge base ID
   * @param {number} count - Number of questions to generate, defaults to 10
   * @returns {Promise} - Generated question list
   */
  generateSampleQuestions: async (dbId, count = 10) => {
    return apiAdminPost(`/api/knowledge/databases/${dbId}/sample-questions`, {
      count
    })
  },

  /**
   * Get test questions for a knowledge base
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Question list
   */
  getSampleQuestions: async (dbId) => {
    return apiAdminGet(`/api/knowledge/databases/${dbId}/sample-questions`)
  }
}

// =============================================================================
// === File management group ===
// =============================================================================

export const fileApi = {
  /**
   * Fetch content from a URL
   * @param {string} url - Target URL
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Fetch result
   */
  fetchUrl: async (url, dbId = null) => {
    return apiAdminPost('/api/knowledge/files/fetch-url', {
      url,
      db_id: dbId
    })
  },

  /**
   * Upload a file
   * @param {File} file - File object
   * @param {string} dbId - Knowledge base ID (optional)
   * @returns {Promise} - Upload result
   */
  uploadFile: async (file, dbId = null) => {
    const formData = new FormData()
    formData.append('file', file)

    const url = dbId ? `/api/knowledge/files/upload?db_id=${dbId}` : '/api/knowledge/files/upload'

    return apiAdminPost(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  },

  /**
   * Get supported file types
   * @returns {Promise} - File type list
   */
  getSupportedFileTypes: async () => {
    return apiAdminGet('/api/knowledge/files/supported-types')
  },

  /**
   * Upload a folder as a zip file
   * @param {File} file - Zip file
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Upload result
   */
  uploadFolder: async (file, dbId) => {
    const formData = new FormData()
    formData.append('file', file)

    // Send FormData directly with apiRequest, but keep the unified error handling
    return apiRequest(
      `/api/knowledge/files/upload-folder?db_id=${dbId}`,
      {
        method: 'POST',
        body: formData
        // Do not set Content-Type; let the browser add the boundary automatically
      },
      true,
      'json'
    ) // Authentication required, expecting a JSON response
  },

  /**
   * Process a folder asynchronously from an uploaded zip file
   * @param {Object} data - Processing parameters
   * @param {string} data.file_path - Uploaded zip file path
   * @param {string} data.db_id - Knowledge base ID
   * @param {string} data.content_hash - File content hash
   * @returns {Promise} - Processing task result
   */
  processFolder: async ({ file_path, db_id, content_hash }) => {
    return apiAdminPost('/api/knowledge/files/process-folder', {
      file_path,
      db_id,
      content_hash
    })
  }
}

// =============================================================================
// === Knowledge base type group ===
// =============================================================================

export const typeApi = {
  /**
   * Get supported knowledge base types
   * @returns {Promise} - Knowledge base type list
   */
  getKnowledgeBaseTypes: async () => {
    return apiAdminGet('/api/knowledge/types')
  },

  /**
   * Get knowledge base statistics
   * @returns {Promise} - Statistics
   */
  getStatistics: async () => {
    return apiAdminGet('/api/knowledge/stats')
  }
}

// =============================================================================
// === Embedding model status check group ===
// =============================================================================

export const embeddingApi = {
  /**
   * Get the status of a specific embedding model
   * @param {string} modelId - Model ID
   * @returns {Promise} - Model status
   */
  getModelStatus: async (modelId) => {
    return apiAdminGet(`/api/knowledge/embedding-models/${modelId}/status`)
  },

  /**
   * Get the status of all embedding models
   * @returns {Promise} - All model statuses
   */
  getAllModelsStatus: async () => {
    return apiAdminGet('/api/knowledge/embedding-models/status')
  }
}

// =============================================================================
// === RAG evaluation group ===
// =============================================================================

export const evaluationApi = {
  /**
   * Upload an evaluation benchmark file
   * @param {string} dbId - Knowledge base ID
   * @param {File} file - JSONL file
   * @param {Object} metadata - Benchmark metadata
   * @returns {Promise} - Upload result
   */
  uploadBenchmark: async (dbId, file, metadata = {}) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', metadata.name || '')
    formData.append('description', metadata.description || '')

    return apiAdminPost(`/api/evaluation/databases/${dbId}/benchmarks/upload`, formData)
  },

  /**
   * Get the benchmark list
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Benchmark list
   */
  getBenchmarks: async (dbId) => {
    return apiAdminGet(`/api/evaluation/databases/${dbId}/benchmarks`)
  },

  /**
   * Get benchmark details
   * @param {string} benchmarkId - Benchmark ID
   * @returns {Promise} - Benchmark details
   */
  getBenchmark: async (benchmarkId) => {
    return apiAdminGet(`/api/evaluation/benchmarks/${benchmarkId}`)
  },
  /**
   * Get benchmark details with db_id
   * @param {string} dbId - Knowledge base ID
   * @param {string} benchmarkId - Benchmark ID
   */
  getBenchmarkByDb: async (dbId, benchmarkId, page = 1, pageSize = 50) => {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString()
    })
    return apiAdminGet(`/api/evaluation/databases/${dbId}/benchmarks/${benchmarkId}?${params}`)
  },

  /**
   * Delete a benchmark
   * @param {string} benchmarkId - Benchmark ID
   * @returns {Promise} - Deletion result
   */
  deleteBenchmark: async (benchmarkId) => {
    return apiAdminDelete(`/api/evaluation/benchmarks/${benchmarkId}`)
  },

  /**
   * Download a benchmark
   * @param {string} benchmarkId - Benchmark ID
   * @returns {Promise} - Response object
   */
  downloadBenchmark: async (benchmarkId) => {
    return apiAdminGet(`/api/evaluation/benchmarks/${benchmarkId}/download`, {}, 'blob')
  },

  /**
   * Automatically generate an evaluation benchmark
   * @param {string} dbId - Knowledge base ID
   * @param {Object} params - Generation parameters
   * @param {number} params.count - Number of questions to generate
   * @param {boolean} params.include_answers - Whether to generate answers
   * @param {Object} params.llm_config - LLM configuration
   * @returns {Promise} - Generation result
   */
  generateBenchmark: async (dbId, params) => {
    return apiAdminPost(`/api/evaluation/databases/${dbId}/benchmarks/generate`, params)
  },

  /**
   * Run RAG evaluation
   * @param {string} dbId - Knowledge base ID
   * @param {Object} params - Evaluation parameters
   * @param {string} params.benchmark_id - Benchmark ID
   * @param {Object} params.retrieval_config - Retrieval configuration
   * @returns {Promise} - Evaluation task ID
   */
  runEvaluation: async (dbId, params) => {
    return apiAdminPost(`/api/evaluation/databases/${dbId}/run`, params)
  },

  /**
   * Get evaluation results
   * @param {string} taskId - Task ID
   * @returns {Promise} - Evaluation result
   */
  getEvaluationResults: async (taskId) => {
    // Deprecated: use getEvaluationResultsByDb instead
    return apiAdminGet(`/api/evaluation/${taskId}/results`)
  },

  /**
   * Delete evaluation results
   * @param {string} taskId - Task ID
   * @returns {Promise} - Deletion result
   */
  deleteEvaluationResult: async (taskId) => {
    // Deprecated: use deleteEvaluationResultByDb instead
    return apiAdminDelete(`/api/evaluation/${taskId}`)
  },

  // New endpoints: evaluation result query and deletion with db_id
  getEvaluationResultsByDb: async (dbId, taskId, params = {}) => {
    const queryParams = new URLSearchParams()

    if (params.page) queryParams.append('page', params.page)
    if (params.pageSize) queryParams.append('page_size', params.pageSize)
    if (params.errorOnly !== undefined) queryParams.append('error_only', params.errorOnly)

    const url = `/api/evaluation/databases/${dbId}/results/${taskId}${queryParams.toString() ? '?' + queryParams.toString() : ''}`
    return apiAdminGet(url)
  },
  deleteEvaluationResultByDb: async (dbId, taskId) => {
    return apiAdminDelete(`/api/evaluation/databases/${dbId}/results/${taskId}`)
  },

  /**
   * Get evaluation history for a knowledge base
   * @param {string} dbId - Knowledge base ID
   * @returns {Promise} - Evaluation history list
   */
  getEvaluationHistory: async (dbId) => {
    return apiAdminGet(`/api/evaluation/databases/${dbId}/history`)
  }
}
