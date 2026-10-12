const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'
const WEEKDAY_TEXT = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']

function parseDate(value) {
  if (value === null || value === undefined || value === '') return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d
  }

  const raw = String(value).trim()
  if (!raw) return null

  const normalized =
    /^\d{4}-\d{2}-\d{2}[T ][\d:.]+$/.test(raw) ? `${raw.replace(' ', 'T')}Z` : raw
  const d = new Date(normalized)
  return Number.isNaN(d.getTime()) ? null : d
}

function getParts(date) {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    weekday: 'long',
    hour12: false,
  }).formatToParts(date)

  const out = {}
  for (const part of parts) {
    if (part.type !== 'literal') out[part.type] = part.value
  }
  return {
    year: Number(out.year),
    month: Number(out.month),
    day: Number(out.day),
    hour: out.hour,
    minute: out.minute,
    weekday: out.weekday,
  }
}

function shanghaiDateOnly(parts) {
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day))
}

function daysBetween(a, b) {
  const msPerDay = 24 * 60 * 60 * 1000
  return Math.round((shanghaiDateOnly(a).getTime() - shanghaiDateOnly(b).getTime()) / msPerDay)
}

function isSameWeek(dateParts, nowParts) {
  const diff = daysBetween(dateParts, nowParts)
  const todayIndex = WEEKDAY_TEXT.indexOf(nowParts.weekday)
  const daysSinceMonday = todayIndex === 0 ? 6 : todayIndex - 1
  return diff >= -daysSinceMonday && diff <= 6 - daysSinceMonday
}

export function formatDisplayDate(value, fallback = '-') {
  const date = parseDate(value)
  if (!date) return value ? String(value) : fallback

  const nowParts = getParts(new Date())
  const dateParts = getParts(date)
  const time = `${dateParts.hour}:${dateParts.minute}`
  const dayDiff = daysBetween(dateParts, nowParts)

  if (dayDiff === 0) return time
  if (dayDiff === -1) return `昨天 ${time}`
  if (dateParts.year === nowParts.year && isSameWeek(dateParts, nowParts)) {
    return `${dateParts.weekday} ${time}`
  }
  if (dateParts.year === nowParts.year) {
    return `${dateParts.month}月${dateParts.day}日 ${time}`
  }
  return `${dateParts.year}年${dateParts.month}月${dateParts.day}日 ${time}`
}
