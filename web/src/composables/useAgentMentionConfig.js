import { computed } from 'vue'

const ACADEMIC_KG_OPTION = {
  id: 'infokom_unesa_kg',
  name: 'Infokom Unesa',
  description: 'Curated Neo4j/Milvus academic knowledge graph for GraphRAG Infokom Unesa.'
}

export function useAgentMentionConfig({
  configurableItems,
  agentConfig,
  availableKnowledgeBases,
  availableMcps,
  availableSkills
}) {
  const mentionConfig = computed(() => {
    const configItems = configurableItems.value || {}
    const currentConfig = agentConfig.value || {}
    const allowedKbNames = new Set()
    const allowedMcpNames = new Set()
    const allowedSkillNames = new Set()
    const allowedSubagentNames = new Set()
    const subagentOptionMap = new Map()

    Object.entries(configItems).forEach(([key, item]) => {
      const kind = item?.template_metadata?.kind
      const val = currentConfig[key]

      if (Array.isArray(val)) {
        if (kind === 'knowledges') {
          val.forEach((v) => allowedKbNames.add(v))
        } else if (kind === 'mcps') {
          val.forEach((v) => allowedMcpNames.add(v))
        } else if (kind === 'skills' || key === 'skills') {
          val.forEach((v) => allowedSkillNames.add(v))
        } else if (kind === 'subagents' || key === 'subagents') {
          val.forEach((v) => allowedSubagentNames.add(v))
        }
      }

      if (kind === 'subagents' || key === 'subagents') {
        const options = Array.isArray(item?.options) ? item.options : []
        options.forEach((option) => {
          if (option == null) return

          const value =
            typeof option === 'object'
              ? option.id || option.value || option.name || option.label
              : option
          if (!value) return

          subagentOptionMap.set(value, {
            id: value,
            name: typeof option === 'object' ? option.name || option.label || value : value,
            description: typeof option === 'object' ? option.description || '' : ''
          })
        })
      }
    })

    const effectiveKnowledgeBases = [...(availableKnowledgeBases.value || [])]
    if (
      allowedKbNames.has(ACADEMIC_KG_OPTION.id) &&
      !effectiveKnowledgeBases.some((kb) => kb.name === ACADEMIC_KG_OPTION.id || kb.id === ACADEMIC_KG_OPTION.id)
    ) {
      effectiveKnowledgeBases.unshift(ACADEMIC_KG_OPTION)
    }
    const knowledgeBases = effectiveKnowledgeBases.filter(
      (kb) => allowedKbNames.has(kb.name) || allowedKbNames.has(kb.id)
    )
    const mcps = availableMcps.value.filter((mcp) => allowedMcpNames.has(mcp.name))
    const skills = availableSkills.value.filter((skill) => {
      const skillName = skill.name || ''
      const skillSlug = skill.slug || ''
      return allowedSkillNames.has(skillName) || allowedSkillNames.has(skillSlug)
    })
    const subagents = Array.from(allowedSubagentNames)
      .filter((name) => !!name)
      .map(
        (name) =>
          subagentOptionMap.get(name) || {
            id: name,
            name,
            description: ''
          }
      )

    if (
      !knowledgeBases.length &&
      !mcps.length &&
      !skills.length &&
      !subagents.length
    )
      return null

    return {
      knowledgeBases,
      mcps,
      skills,
      subagents
    }
  })

  return {
    mentionConfig
  }
}
