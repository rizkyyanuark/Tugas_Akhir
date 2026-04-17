import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.extend(relativeTime)
dayjs.locale('en')

const DEFAULT_TZ = 'Asia/Jakarta'
dayjs.tz.setDefault(DEFAULT_TZ)

const NUMERIC_REGEX = /^-?\d+(?:\.\d+)?$/

const coerceDayjs = (value) => {
  if (value === null || value === undefined) {
    return null
  }

  if (typeof value === 'number') {
    return dayjs(value).tz(DEFAULT_TZ)
  }

  const stringValue = String(value).trim()
  if (!stringValue) {
    return null
  }

  if (NUMERIC_REGEX.test(stringValue)) {
    const numeric = Number(stringValue)
    if (Number.isNaN(numeric)) {
      return null
    }

    // If the value is less than 10^12, treat it as a unix timestamp in seconds, otherwise milliseconds.
    if (Math.abs(numeric) < 1e12) {
      return dayjs.unix(numeric).tz(DEFAULT_TZ)
    }
    return dayjs(numeric).tz(DEFAULT_TZ)
  }

  // Parse ISO string (dayjs automatically recognizes timezone info, e.g., Z suffix for UTC)
  // Need to convert to UTC first then set timezone, otherwise .tz() only changes display without correct conversion
  const parsed = dayjs(stringValue)
  if (!parsed.isValid()) {
    return null
  }
  // First convert to UTC (preserving original time value), then convert to Jakarta timezone.
  return parsed.utc().tz(DEFAULT_TZ)
}

export const parseToShanghai = (value) => coerceDayjs(value)

export const formatDateTime = (value, format = 'YYYY-MM-DD HH:mm') => {
  const parsed = coerceDayjs(value)
  if (!parsed) return '-'
  return parsed.format(format)
}

export const formatFullDateTime = (value) => formatDateTime(value, 'YYYY-MM-DD HH:mm:ss')

export const formatRelative = (value) => {
  const parsed = coerceDayjs(value)
  if (!parsed) return '-'
  return parsed.fromNow()
}

export const sortByDatetimeDesc = (items, accessor) => {
  const copy = [...items]
  copy.sort((a, b) => {
    const first = coerceDayjs(accessor(a))
    const second = coerceDayjs(accessor(b))

    if (!first && !second) return 0
    if (!first) return 1
    if (!second) return -1
    return second.valueOf() - first.valueOf()
  })
  return copy
}

export default dayjs
