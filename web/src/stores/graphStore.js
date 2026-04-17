import { defineStore } from 'pinia'
import { DirectedGraph } from 'graphology'

export const useGraphStore = defineStore('graph', {
  state: () => ({
    // Selection and focus state
    selectedNode: null,
    focusedNode: null,
    selectedEdge: null,
    focusedEdge: null,

    // Graph data
    rawGraph: null,
    sigmaGraph: null,
    sigmaInstance: null,

    // Entity type and color mapping
    entityTypes: [],
    typeColorMap: new Map(),

    // Loading state
    isFetching: false,
    graphIsEmpty: false,

    // Flag to move to selected node
    moveToSelectedNode: false,

    // Graph statistics
    stats: {
      displayed_nodes: 0,
      displayed_edges: 0,
      is_truncated: false
    }
  }),

  getters: {
    // Get detailed info of selected node
    selectedNodeData: (state) => {
      if (!state.selectedNode || !state.rawGraph) return null
      return state.rawGraph.nodes.find((node) => node.id === state.selectedNode)
    },

    // Get detailed info of selected edge
    selectedEdgeData: (state) => {
      if (!state.selectedEdge || !state.rawGraph) return null

      console.log('Finding edge data, selected edge ID:', state.selectedEdge)

      // First try matching through dynamicId (format used by Sigma)
      let foundEdge = state.rawGraph.edges.find((edge) => edge.dynamicId === state.selectedEdge)
      if (foundEdge) {
        console.log('Found edge via dynamicId:', foundEdge)
        return foundEdge
      }

      // If not found, try matching through original ID
      foundEdge = state.rawGraph.edges.find((edge) => edge.id === state.selectedEdge)
      if (foundEdge) {
        console.log('Found edge via id:', foundEdge)
        return foundEdge
      }

      // For dynamicId with format source-target-index, also try parsing
      const dynamicIdPattern = /^(.+)-(.+)-(\d+)$/
      const match = state.selectedEdge.match(dynamicIdPattern)
      if (match) {
        const [, source, target] = match
        foundEdge = state.rawGraph.edges.find(
          (edge) => edge.source === source && edge.target === target
        )
        if (foundEdge) {
          console.log('Found edge via parsing dynamicId:', foundEdge)
          return foundEdge
        }
      }

      // Finally try matching through source->target format
      const arrowPattern = /^(.+)->(.+)$/
      const arrowMatch = state.selectedEdge.match(arrowPattern)
      if (arrowMatch) {
        const [, source, target] = arrowMatch
        foundEdge = state.rawGraph.edges.find(
          (edge) => edge.source === source.trim() && edge.target === target.trim()
        )
        if (foundEdge) {
          console.log('Found edge via arrow format:', foundEdge)
          return foundEdge
        }
      }

      console.warn('No matching edge data found, selected edge ID:', state.selectedEdge)
      return null
    },

    // Check if graph is empty
    isGraphEmpty: (state) => {
      return !state.rawGraph || state.rawGraph.nodes.length === 0
    }
  },

  actions: {
    // Set Sigma instance
    setSigmaInstance(instance) {
      this.sigmaInstance = instance
    },

    // Node selection and focus
    setSelectedNode(nodeId, moveToNode = false) {
      this.selectedNode = nodeId
      this.moveToSelectedNode = moveToNode
      // If node selected, clear selected edge
      if (nodeId) {
        this.selectedEdge = null
      }
    },

    setFocusedNode(nodeId) {
      this.focusedNode = nodeId
    },

    setSelectedEdge(edgeId) {
      this.selectedEdge = edgeId
      // If edge selected, clear selected node
      if (edgeId) {
        this.selectedNode = null
      }
    },

    setFocusedEdge(edgeId) {
      this.focusedEdge = edgeId
    },

    // Clear all selections
    clearSelection() {
      this.selectedNode = null
      this.focusedNode = null
      this.selectedEdge = null
      this.focusedEdge = null
    },

    // Set loading state
    setIsFetching(isFetching) {
      this.isFetching = isFetching
    },

    // Set entity types
    setEntityTypes(types) {
      this.entityTypes = types
      this.updateTypeColorMap()
    },

    // Update type color map
    updateTypeColorMap() {
      const colorPalette = [
        '#FF6B6B', // Person - Red
        '#4ECDC4', // Organization - Cyan
        '#45B7D1', // Location - Blue
        '#96CEB4', // Event - Green
        '#FFEAA7', // Category - Yellow
        '#DDA0DD', // Device - Purple
        '#FF7675', // Athlete - Red
        '#FD79A8', // Record - Pink
        '#FDCB6E', // Year - Orange
        '#B2BEC3' // Unknown - Grey
      ]

      const typeColorMap = new Map()
      this.entityTypes.forEach((type, index) => {
        const colorIndex = index % colorPalette.length
        typeColorMap.set(type.type, colorPalette[colorIndex])
      })

      // Set fixed colors for special types
      typeColorMap.set('person', '#FF6B6B')
      typeColorMap.set('organization', '#4ECDC4')
      typeColorMap.set('location', '#45B7D1')
      typeColorMap.set('geo', '#45B7D1')
      typeColorMap.set('event', '#96CEB4')
      typeColorMap.set('category', '#FFEAA7')
      typeColorMap.set('unknown', '#B2BEC3')

      this.typeColorMap = typeColorMap
    },

    // Get entity type color
    getEntityColor(entityType) {
      return this.typeColorMap.get(entityType) || '#B2BEC3'
    },

    // Set raw graph data
    setRawGraph(rawGraph) {
      this.rawGraph = rawGraph
      this.graphIsEmpty = !rawGraph || rawGraph.nodes.length === 0
      this.updateStats()
    },

    // Set Sigma graph data
    setSigmaGraph(sigmaGraph) {
      this.sigmaGraph = sigmaGraph
    },

    // Update statistics
    updateStats() {
      if (this.rawGraph) {
        this.stats = {
          displayed_nodes: this.rawGraph.nodes.length,
          displayed_edges: this.rawGraph.edges.length,
          is_truncated: this.rawGraph.is_truncated ?? this.stats?.is_truncated ?? false
        }
      }
    },

    // Create graph data structure from API data
    createGraphFromApiData(nodesData, edgesData) {
      const rawGraph = {
        nodes: [],
        edges: [],
        nodeIdMap: {},
        edgeIdMap: {},
        edgeDynamicIdMap: {}
      }

      console.log('Processing nodes data:', nodesData)

      // Process node data
      nodesData.forEach((node, index) => {
        // Adapt to new LightRAG API format
        const nodeId = String(node.id)
        const labels = node.labels || [node.entity_type || 'unknown']
        const entityType = node.entity_type || labels[0] || 'unknown'

        const processedNode = {
          id: nodeId,
          labels: Array.isArray(labels) ? labels.map(String) : [String(labels)],
          entity_type: String(entityType),
          properties: {
            entity_id: String(node.properties?.entity_id || node.entity_id || nodeId),
            entity_type: String(entityType),
            description: String(node.properties?.description || node.description || ''),
            file_path: String(node.properties?.file_path || node.file_path || ''),
            ...(node.properties || {})
          },
          // Properties needed by Sigma.js
          size: this.calculateNodeSize(node),
          x: Math.random() * 1000, // Random initial position
          y: Math.random() * 1000,
          color: this.getEntityColor(String(entityType)),
          degree: 0 // Will be calculated when processing edges
        }

        rawGraph.nodes.push(processedNode)
        rawGraph.nodeIdMap[nodeId] = index
      })

      // Calculate node degrees
      const nodeDegrees = {}
      edgesData.forEach((edge) => {
        const sourceId = String(edge.source)
        const targetId = String(edge.target)
        nodeDegrees[sourceId] = (nodeDegrees[sourceId] || 0) + 1
        nodeDegrees[targetId] = (nodeDegrees[targetId] || 0) + 1
      })

      // Update node degrees and sizes
      rawGraph.nodes.forEach((node) => {
        node.degree = nodeDegrees[node.id] || 0
        node.size = this.calculateNodeSize({ degree: node.degree })
      })

      console.log('Processing edges data:', edgesData)

      // Process edge data
      edgesData.forEach((edge, index) => {
        const sourceId = String(edge.source)
        const targetId = String(edge.target)
        const dynamicId = `${sourceId}-${targetId}-${index}`

        // Adapt to new LightRAG API format
        const weight = Number(edge.properties?.weight || edge.weight || 1.0)

        const processedEdge = {
          id: String(edge.id),
          source: sourceId,
          target: targetId,
          type: edge.type || 'DIRECTED',
          properties: {
            weight: weight,
            keywords: String(edge.properties?.keywords || edge.keywords || ''),
            description: String(edge.properties?.description || edge.description || ''),
            file_path: String(edge.properties?.file_path || edge.file_path || ''),
            ...(edge.properties || {})
          },
          dynamicId: dynamicId,
          // Properties needed by Sigma.js
          size: this.calculateEdgeSize(weight),
          color: '#666',
          originalWeight: weight
        }

        rawGraph.edges.push(processedEdge)
        rawGraph.edgeIdMap[edge.id] = index
        rawGraph.edgeDynamicIdMap[dynamicId] = index
      })

      return rawGraph
    },

    // Calculate node size
    calculateNodeSize(node) {
      const baseSizeM = 15
      const degree = node.degree || 0
      return Math.min(baseSizeM + degree * 3, 40)
    },

    // Calculate edge size
    calculateEdgeSize(weight) {
      const minSize = 3 // Keep consistent with Sigma's minEdgeThickness
      const maxSize = 8 // Keep consistent with Sigma's maxEdgeThickness
      const normalizedWeight = Math.max(0, Math.min(1, (weight - 1) / 9)) // Assume weight range 1-10
      return minSize + normalizedWeight * (maxSize - minSize)
    },

    // Create Sigma graph instance
    createSigmaGraph(rawGraph) {
      console.log(
        'Starting Sigma graph creation, node count:',
        rawGraph.nodes.length,
        'edge count:',
        rawGraph.edges.length
      )
      const sigmaGraph = new DirectedGraph()

      // Add nodes
      rawGraph.nodes.forEach((node) => {
        // Ensure all attributes are correct types
        const nodeAttributes = {
          label: String(node.properties?.entity_id || node.id),
          size: Number(node.size) || 15,
          color: String(node.color) || '#B2BEC3',
          x: Number(node.x) || Math.random() * 1000,
          y: Number(node.y) || Math.random() * 1000,
          // Save original data reference
          originalData: node
        }

        sigmaGraph.addNode(String(node.id), nodeAttributes)
      })

      console.log('Node addition complete, starting edge addition...')

      // Add edges
      let edgeAddedCount = 0
      let edgeSkippedCount = 0
      rawGraph.edges.forEach((edge, index) => {
        // Add debug info
        if (index < 3) {
          console.log('Processing edge #' + index + ':', {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            dynamicId: edge.dynamicId,
            edgeObject: edge
          })
        }

        if (sigmaGraph.hasNode(String(edge.source)) && sigmaGraph.hasNode(String(edge.target))) {
          // Ensure all attributes are correct types
          const edgeAttributes = {
            size: Number(edge.size) || 1,
            color: String(edge.color) || '#666',
            label: String(edge.properties?.keywords || edge.properties?.description || ''),
            originalWeight: Number(edge.originalWeight) || 1,
            // Save original data reference
            originalData: edge
          }

          // Use standard addEdge method: addEdge(edgeId, source, target, attributes)
          try {
            // Use dynamic ID as Sigma edge ID to avoid duplicates
            const sigmaEdgeId = edge.dynamicId || `${edge.source}->${edge.target}`

            // Check if same edge already exists
            if (!sigmaGraph.hasEdge(sigmaEdgeId)) {
              sigmaGraph.addEdgeWithKey(
                sigmaEdgeId,
                String(edge.source),
                String(edge.target),
                edgeAttributes
              )
              edgeAddedCount++
            } else {
              edgeSkippedCount++
            }
          } catch (err) {
            console.warn('Failed to add edge:', {
              source: edge.source,
              target: edge.target,
              attributes: edgeAttributes,
              error: err.message
            })
          }
        } else {
          console.warn('Node does not exist, skipping edge:', {
            source: edge.source,
            target: edge.target,
            hasSource: sigmaGraph.hasNode(String(edge.source)),
            hasTarget: sigmaGraph.hasNode(String(edge.target))
          })
        }
      })

      console.log(`Edge addition complete: Success ${edgeAddedCount}, Skipped ${edgeSkippedCount}`)

      return sigmaGraph
    },

    // Reset all states
    reset() {
      this.selectedNode = null
      this.focusedNode = null
      this.selectedEdge = null
      this.focusedEdge = null
      this.rawGraph = null
      this.sigmaGraph = null
      this.moveToSelectedNode = false
      this.graphIsEmpty = false
      this.stats = {
        displayed_nodes: 0,
        displayed_edges: 0,
        is_truncated: false
      }
    }
  }
})
