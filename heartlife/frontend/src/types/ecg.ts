export type EcgPeriod = 'day' | 'month' | 'year'

export interface EcgLink {
  enabled: boolean
  linked: boolean
  ecg_username: string | null
  expires_at: number | null
  ecg_url: string | null
  revocation_pending: boolean
}

export interface EcgBucket {
  index: number
  label: string
  records: number
  duration_s: number
  hr_mean: number | null
  hr_records: number
}

export interface EcgSummary {
  ecg_user: { id: string; username: string }
  expires_at: number
  recent_records: Array<{
    session_id: string
    started_utc: string
    duration_s: number
    hr_mean: number | null
    report_url?: string | null
  }>
  trends: {
    period: EcgPeriod
    anchor: string
    utc_offset_minutes: number
    buckets: EcgBucket[]
    total_records: number
    total_duration_s: number
    note: string
  }
}
