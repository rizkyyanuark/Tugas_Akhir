import { apiGet, apiPost } from './base'

/**
 * Graph database API module
 * Includes both LightRAG graph knowledge base and Neo4j graph database interfaces
 * Uses a namespace grouping pattern to clearly separate interface types
 */

// =============================================================================
// === Unified Graph API ===
// =============================================================================

export const unifiedApi = {
  /**
   * Get the list of all available knowledge graphs
   * @returns {Promise} - Graph list
   */
  getGraphs: async () => {
    return await apiGet('/api/graph/list', {}, true)
  },

  /**
   * Get subgraph data (unified interface)
   * @param {Object} params - Query parameters
   * @param {string} params.db_id - Graph ID
   * @param {string} params.node_label - Node label/keyword
   * @param {number} params.max_depth - Maximum depth
   * @param {number} params.max_nodes - Maximum node count
   * @returns {Promise} - Subgraph data
   */
  getSubgraph: async (params) => {
    const { db_id, node_label = '*', max_depth = 2, max_nodes = 100 } = params

    if (!db_id) {
      throw new Error('db_id is required')
    }

    const queryParams = new URLSearchParams({
      db_id: db_id,
      node_label: node_label,
      max_depth: max_depth.toString(),
      max_nodes: max_nodes.toString()
    })

    return await apiGet(`/api/graph/subgraph?${queryParams.toString()}`, {}, true)
  },

  /**
   * Get graph statistics (unified interface)
   * @param {string} db_id - Graph ID
   * @returns {Promise} - Statistics
   */
  getStats: async (db_id) => {
    if (!db_id) {
      throw new Error('db_id is required')
    }

    const queryParams = new URLSearchParams({
      db_id: db_id
    })

    return await apiGet(`/api/graph/stats?${queryParams.toString()}`, {}, true)
  },

  /**
   * Get graph label list (unified interface)
   * @param {string} db_id - Graph ID
   * @returns {Promise} - Label list
   */
  getLabels: async (db_id) => {
    if (!db_id) {
      throw new Error('db_id is required')
    }

    const queryParams = new URLSearchParams({
      db_id: db_id
    })

    return await apiGet(`/api/graph/labels?${queryParams.toString()}`, {}, true)
  }
}

// =============================================================================
// === Neo4j graph database interface group ===
// =============================================================================

export const neo4jApi = {
  /**
   * Get sample nodes from the Neo4j graph database
   * @param {string} kgdb_name - Neo4j database name (defaults to 'neo4j')
   * @param {number} num - Number of nodes
   * @returns {Promise} - Sample node data
   */
  getSampleNodes: async (kgdb_name = 'neo4j', num = 100) => {
    const queryParams = new URLSearchParams({
      kgdb_name: kgdb_name,
      num: num.toString()
    })

    return await apiGet(`/api/graph/neo4j/nodes?${queryParams.toString()}`, {}, true)
  },

  /**
   * Query Neo4j graph nodes by entity name
   * @param {string} entity_name - Entity name
   * @returns {Promise} - Node data
   */
  queryNode: async (entity_name) => {
    if (!entity_name) {
      throw new Error('entity_name is required')
    }

    const queryParams = new URLSearchParams({
      entity_name: entity_name
    })

    return await apiGet(`/api/graph/neo4j/node?${queryParams.toString()}`, {}, true)
  },

  /**
   * Add graph entities to Neo4j from a JSONL file
   * @param {string} file_path - JSONL file path
   * @param {string} kgdb_name - Neo4j database name (defaults to 'neo4j')
   * @param {string} embed_model_name - Embedding model name (optional)
   * @param {number} batch_size - Batch size (optional)
   * @returns {Promise} - Add result
   */
  addEntities: async (
    file_path,
    kgdb_name = 'neo4j',
    embed_model_name = null,
    batch_size = null
  ) => {
    return await apiPost(
      '/api/graph/neo4j/add-entities',
      {
        file_path: file_path,
        kgdb_name: kgdb_name,
        embed_model_name: embed_model_name,
        batch_size: batch_size
      },
      {},
      true
    )
  },

  /**
   * Add an embedding index for Neo4j graph nodes
   * @param {string} kgdb_name - Neo4j database name (defaults to 'neo4j')
   * @returns {Promise} - Index result
   */
  indexEntities: async (kgdb_name = 'neo4j') => {
    return await apiPost(
      '/api/graph/neo4j/index-entities',
      {
        kgdb_name: kgdb_name
      },
      {},
      true
    )
  },

  /**
   * Get Neo4j graph database information
   * @returns {Promise} - Graph database information
   */
  getInfo: async () => {
    return await apiGet('/api/graph/neo4j/info', {}, true)
  }
}

// =============================================================================
// === Utility function group ===
// =============================================================================

/**
 * Get a color by entity type
 * @param {string} entityType - Entity type
 * @returns {string} - Color value
 */
export const getEntityTypeColor = (entityType) => {
  const colorMap = {
    person: '#FF6B6B', // Red - people
    organization: '#4ECDC4', // Cyan - organizations
    location: '#45B7D1', // Blue - locations
    geo: '#45B7D1', // Blue - geographic locations
    event: '#96CEB4', // Green - events
    category: '#FFEAA7', // Yellow - categories
    equipment: '#DDA0DD', // Purple - equipment
    athlete: '#FF7675', // Red - athletes
    record: '#FD79A8', // Pink - records
    year: '#FDCB6E', // Orange - years
    UNKNOWN: '#B2BEC3', // Gray - unknown
    unknown: '#B2BEC3' // Gray - unknown
  }

  return colorMap[entityType] || colorMap['unknown']
}

/**
 * Calculate edge width from weight
 * @param {number} weight - Weight value
 * @param {number} minWeight - Minimum weight
 * @param {number} maxWeight - Maximum weight
 * @returns {number} - Edge width
 */
export const calculateEdgeWidth = (weight, minWeight = 1, maxWeight = 10) => {
  const minWidth = 1
  const maxWidth = 5
  const normalizedWeight = (weight - minWeight) / (maxWeight - minWeight)
  return minWidth + normalizedWeight * (maxWidth - minWidth)
}

// =============================================================================
// === Compatibility exports (optional, for smooth migration) ===
// =============================================================================

// Keep backward-compatible exports; they can be removed later
export const getGraphNodes = async (params = {}) => {
  console.warn('getGraphNodes is deprecated, use neo4jApi.getSampleNodes instead')
  return neo4jApi.getSampleNodes(params.kgdb_name || 'neo4j', params.num || 100)
}

export const getGraphNode = async (params = {}) => {
  console.warn('getGraphNode is deprecated, use neo4jApi.queryNode instead')
  return neo4jApi.queryNode(params.entity_name)
}

export const addByJsonl = async (file_path, kgdb_name = 'neo4j') => {
  console.warn('addByJsonl is deprecated, use neo4jApi.addEntities instead')
  return neo4jApi.addEntities(file_path, kgdb_name)
}

export const indexNodes = async (kgdb_name = 'neo4j') => {
  console.warn('indexNodes is deprecated, use neo4jApi.indexEntities instead')
  return neo4jApi.indexEntities(kgdb_name)
}

export const getGraphStats = async () => {
  console.warn('getGraphStats is deprecated, use neo4jApi.getInfo instead')
  return neo4jApi.getInfo()
}

// Compatibility exports - use the unified interface to replace the legacy graphApi
export const graphApi = {
  // Use the unified interface instead of the LightRAG interface
  getSubgraph: unifiedApi.getSubgraph,
  getDatabases: async () => {
    // Use the unified interface to get all graphs, then filter out the LightRAG ones
    const response = await unifiedApi.getGraphs()
    if (response.success) {
      const lightragDbs = response.data.filter((graph) => graph.type === 'lightrag')
      return { success: true, data: { databases: lightragDbs } }
    }
    return response
  },
  getLabels: unifiedApi.getLabels,
  getStats: unifiedApi.getStats,
  // Keep the Neo4j interface
  ...neo4jApi
}
