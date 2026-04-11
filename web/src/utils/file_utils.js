// File utility helpers
import {
  FileTextFilled,
  FileMarkdownFilled,
  FilePdfFilled,
  FileWordFilled,
  FileExcelFilled,
  FileImageFilled,
  FileUnknownFilled,
  FilePptFilled,
  LinkOutlined
} from '@ant-design/icons-vue'
import { formatRelative, parseToShanghai } from '@/utils/time'

// Get a file icon by extension
export const getFileIcon = (filename) => {
  if (!filename) return FileUnknownFilled

  // Check if it's a URL
  if (filename.startsWith('http://') || filename.startsWith('https://')) {
    return LinkOutlined
  }

  const extension = filename.toLowerCase().split('.').pop()

  const iconMap = {
    // Text files
    txt: FileTextFilled,
    text: FileTextFilled,
    log: FileTextFilled,

    // Markdown files
    md: FileMarkdownFilled,
    markdown: FileMarkdownFilled,

    // PDF files
    pdf: FilePdfFilled,

    // Word documents
    doc: FileWordFilled,
    docx: FileWordFilled,

    // Excel documents
    xls: FileExcelFilled,
    xlsx: FileExcelFilled,
    csv: FileExcelFilled,

    // PowerPoint documents
    ppt: FilePptFilled,
    pptx: FilePptFilled,

    // Image files
    jpg: FileImageFilled,
    jpeg: FileImageFilled,
    png: FileImageFilled,
    gif: FileImageFilled,
    bmp: FileImageFilled,
    svg: FileImageFilled,
    webp: FileImageFilled,

    // HTML files
    html: FileTextFilled,
    htm: FileTextFilled
  }

  return iconMap[extension] || FileUnknownFilled
}

// Get a file icon color by extension
export const getFileIconColor = (filename) => {
  if (!filename) return '#8c8c8c'

  // Check if it's a URL
  if (filename.startsWith('http://') || filename.startsWith('https://')) {
    return '#1890ff' // Blue for links
  }

  const extension = filename.toLowerCase().split('.').pop()

  const colorMap = {
    // Text files - blue
    txt: '#1890ff',
    text: '#1890ff',
    log: '#1890ff',

    // Markdown files - dark gray
    md: '#595959',
    markdown: '#595959',

    // PDF files - red
    pdf: '#ff4d4f',

    // Word documents - dark blue
    doc: '#2f54eb',
    docx: '#2f54eb',

    // Excel documents - green
    xls: '#52c41a',
    xlsx: '#52c41a',
    csv: '#52c41a',

    // PowerPoint documents - orange
    ppt: '#f6720d',
    pptx: '#f6720d',

    // Image files - purple
    jpg: '#722ed1',
    jpeg: '#722ed1',
    png: '#722ed1',
    gif: '#722ed1',
    bmp: '#722ed1',
    svg: '#722ed1',
    webp: '#722ed1',

    // HTML files - orange
    html: '#fa8c16',
    htm: '#fa8c16'
  }

  return colorMap[extension] || '#8c8c8c'
}

// Format relative time with CST baseline
export const formatRelativeTime = (value) => formatRelative(value)

// Format standard time
export const formatStandardTime = (value) => {
  const parsed = parseToShanghai(value)
  if (!parsed) return '-'
  return parsed.format('YYYY-MM-DD HH:mm:ss')
}

// Get status text
export const getStatusText = (status) => {
  const statusMap = {
    done: 'Completed',
    failed: 'Failed',
    processing: 'Processing',
    waiting: 'Waiting'
  }
  return statusMap[status] || status
}

// Format file size
export const formatFileSize = (bytes) => {
  if (bytes === 0 || bytes === '0') return '0 B'
  if (!bytes) return '-'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}
