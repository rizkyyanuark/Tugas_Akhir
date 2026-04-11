export const CHUNK_PRESET_OPTIONS = [
  {
    value: 'general',
    label: 'General',
    description: 'General chunking: split by separators and length, suitable for most standard documents.'
  },
  {
    value: 'qa',
    label: 'QA',
    description: 'QA chunking: prioritize extracting question-answer structure, suitable for FAQs, question banks, and Q&A manuals.'
  },
  {
    value: 'book',
    label: 'Book',
    description: 'Book chunking: strengthen chapter heading detection and hierarchical merging, suitable for textbooks, manuals, and long chaptered documents.'
  },
  {
    value: 'laws',
    label: 'Laws',
    description: 'Laws chunking: organize and merge by legal article hierarchy, suitable for laws, regulations, and policy documents.'
  }
]

export const CHUNK_PRESET_LABEL_MAP = Object.fromEntries(
  CHUNK_PRESET_OPTIONS.map((item) => [item.value, item.label])
)

export const CHUNK_PRESET_DESCRIPTION_MAP = Object.fromEntries(
  CHUNK_PRESET_OPTIONS.map((item) => [item.value, item.description])
)

export const getChunkPresetDescription = (presetId) =>
  CHUNK_PRESET_DESCRIPTION_MAP[presetId] || CHUNK_PRESET_DESCRIPTION_MAP.general
