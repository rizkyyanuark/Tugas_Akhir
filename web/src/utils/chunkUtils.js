/**
 * Chunk merging utility functions
 * Used to merge multiple chunks and handle overlapping content
 */

/**
 * Finds the overlap between two strings
 * @param {string} str1 - First string
 * @param {string} str2 - Second string
 * @returns {string} - Overlapping content
 */
export function findOverlap(str1, str2) {
  if (!str1 || !str2) return ''

  const maxOverlap = Math.min(str1.length, str2.length)
  let overlap = ''

  // Start checking from the longest possible overlap
  for (let i = maxOverlap; i > 10; i--) {
    const endStr1 = str1.slice(-i)
    const startStr2 = str2.slice(0, i)

    if (endStr1 === startStr2) {
      overlap = endStr1
      break
    }
  }

  return overlap
}

/**
 * Merges chunks and handles overlapping content
 * @param {Array} chunks - Array of chunks, each containing id, content, chunk_order_index
 * @returns {Object} - Merge result, containing content and chunks array
 */
export function mergeChunks(chunks) {
  if (!chunks || chunks.length === 0) {
    return { content: '', chunks: [] }
  }

  // Sort by order_index
  const sorted = [...chunks].sort((a, b) => a.chunk_order_index - b.chunk_order_index)
  const merged = []
  let currentContent = ''

  for (let i = 0; i < sorted.length; i++) {
    const chunk = sorted[i]
    const content = chunk.content

    if (i === 0) {
      // Add first chunk directly
      currentContent = content
      merged.push({
        ...chunk,
        startOffset: 0,
        endOffset: content.length
      })
    } else {
      // Find overlap
      const overlap = findOverlap(currentContent, content)
      const newContent = content.slice(overlap.length)

      if (newContent.length > 0) {
        const startOffset = currentContent.length
        if (overlap.length > 0) {
          currentContent += newContent
        } else {
          currentContent += `\n${newContent}`
        }
        merged.push({
          ...chunk,
          startOffset,
          endOffset: currentContent.length
        })
      }
    }
  }

  return { content: currentContent, chunks: merged }
}

/**
 * Splits text into paragraphs
 * @param {string} content - Text content
 * @returns {Array} - Array of paragraphs
 */
export function splitIntoParagraphs(content) {
  if (!content) return []

  // Split by multiple newlines, filter empty paragraphs
  return content.split(/\n\n+/).filter((para) => para.trim() !== '')
}

/**
 * Maps each paragraph to its corresponding chunk
 * @param {Array} paragraphs - Array of paragraphs
 * @param {Array} mappedChunks - Mapped chunks
 * @returns {Array} - Paragraphs with chunk information
 */
export function mapParagraphsToChunks(paragraphs, mappedChunks) {
  if (!paragraphs || !mappedChunks) return []

  let currentOffset = 0
  return paragraphs.map((paragraph) => {
    const paragraphLength = paragraph.length + 2 // +2 for the \n\n

    // Find chunk containing this position
    const chunk =
      mappedChunks.find(
        (chunk) => currentOffset >= chunk.startOffset && currentOffset < chunk.endOffset
      ) || mappedChunks[0]

    const result = {
      content: paragraph,
      chunk,
      startOffset: currentOffset,
      endOffset: currentOffset + paragraphLength
    }

    currentOffset += paragraphLength
    return result
  })
}

/**
 * Gets preview text for a chunk
 * @param {string} content - Chunk content
 * @param {number} maxLength - Maximum length
 * @returns {string} - Preview text
 */
export function getChunkPreview(content, maxLength = 100) {
  if (!content) return ''

  const text = content.replace(/\n+/g, ' ').trim()
  if (text.length <= maxLength) return text

  return text.slice(0, maxLength) + '...'
}
