import type { MoodValue } from '../types/api'

export const MOOD_OPTIONS: Array<{ value: MoodValue; label: string }> = [
  { value: 'very_good', label: '很好' },
  { value: 'good', label: '较好' },
  { value: 'neutral', label: '一般' },
  { value: 'bad', label: '较差' },
  { value: 'very_bad', label: '很差' },
]

export const MOOD_LABELS: Record<string, string> = {
  very_good: '很好',
  good: '较好',
  neutral: '一般',
  bad: '较差',
  very_bad: '很差',
}

export const WEEKDAY_OPTIONS = [
  { day: 1, short: '一', full: '周一' },
  { day: 2, short: '二', full: '周二' },
  { day: 3, short: '三', full: '周三' },
  { day: 4, short: '四', full: '周四' },
  { day: 5, short: '五', full: '周五' },
  { day: 6, short: '六', full: '周六' },
  { day: 7, short: '日', full: '周日' },
]

export const COMMUNITY_CATEGORIES = [
  '日常健康',
  '运动与习惯',
  '睡眠与休息',
  '心脏健康科普交流',
  '设备使用经验',
]

export const REPORT_REASON_OPTIONS = [
  { value: 'misleading_medical', label: '误导性健康建议' },
  { value: 'privacy', label: '隐私泄露' },
  { value: 'spam', label: '广告刷屏' },
  { value: 'harassment', label: '不友善内容' },
  { value: 'other', label: '其他' },
]

export function formatMood(mood: string | null | undefined): string {
  if (!mood) return '未记录'
  return MOOD_LABELS[mood] || mood
}

export function formatLocalDateToday(tz?: string): string {
  try {
    const formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz || 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
    const formatted = formatter.format(new Date())
    if (/^\d{4}-\d{2}-\d{2}$/.test(formatted)) {
      return formatted
    }
  } catch {
    // Fallback below
  }
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function formatDateTimeShort(iso: string | null | undefined): string {
  if (!iso) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${hh}:${mm}`
}

export function getMondayOfDate(dateStr: string): string {
  const parts = dateStr.split('-').map(Number)
  const d = new Date(Date.UTC(parts[0], (parts[1] || 1) - 1, parts[2] || 1))
  const day = d.getUTCDay() // 0 Sun .. 6 Sat
  const diff = day === 0 ? -6 : 1 - day
  d.setUTCDate(d.getUTCDate() + diff)
  return d.toISOString().slice(0, 10)
}

export function shiftIsoDate(dateStr: string, deltaDays: number): string {
  const parts = dateStr.split('-').map(Number)
  const d = new Date(Date.UTC(parts[0], (parts[1] || 1) - 1, parts[2] || 1))
  d.setUTCDate(d.getUTCDate() + deltaDays)
  return d.toISOString().slice(0, 10)
}

export function weekdaysToMask(days: number[]): number {
  let mask = 0
  for (const d of days) {
    if (d >= 1 && d <= 7) {
      mask |= 1 << (d - 1)
    }
  }
  return mask || 127
}

export function maskToWeekdays(mask: number | undefined | null): number[] {
  if (typeof mask !== 'number' || mask <= 0) return [1, 2, 3, 4, 5, 6, 7]
  const days: number[] = []
  for (let d = 1; d <= 7; d++) {
    if ((mask & (1 << (d - 1))) !== 0) {
      days.push(d)
    }
  }
  return days.length > 0 ? days : [1, 2, 3, 4, 5, 6, 7]
}

export function formatWeekdaysLabel(days?: number[], mask?: number): string {
  const list = Array.isArray(days) && days.length > 0 ? days : maskToWeekdays(mask)
  if (list.length === 7) return '每天'
  if (list.length === 5 && [1, 2, 3, 4, 5].every((x) => list.includes(x))) return '工作日'
  return (
    '周' +
    WEEKDAY_OPTIONS.filter((w) => list.includes(w.day))
      .map((w) => w.short)
      .join('、')
  )
}

export function splitPlainParagraphs(text: string | null | undefined): string[] {
  if (!text) return []
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
}

export function isSafeHttpUrl(url: string | null | undefined): boolean {
  if (!url || typeof url !== 'string') return false
  const trimmed = url.trim()
  if (!trimmed.startsWith('https://') && !trimmed.startsWith('http://')) return false
  try {
    const parsed = new URL(trimmed)
    return (parsed.protocol === 'https:' || parsed.protocol === 'http:') && Boolean(parsed.hostname)
  } catch {
    return false
  }
}

export function makeRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}
