export type EcgPeriod = 'day' | 'month' | 'year'

export interface EcgLink {
  enabled: boolean
  linked: boolean
  ecg_username: string | null
  expires_at: number | null
  ecg_url: string | null
  revocation_pending: boolean
  measurement_allowed?: boolean
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
  measurement_allowed?: boolean
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

export interface EcgEnvelope {
  ecg_user: { id: string; username: string }
  expires_at: number
  measurement_allowed: boolean
}

export interface EcgDevice {
  device_id: string
  label: string
  online: boolean
  ready: boolean
  reason: string
}

export type EcgMeasurementStatus = 'queued' | 'accepted' | 'recording' | 'uploading' | 'completed' | 'expired' | 'failed'
export type EcgAnalysisStatus = 'not_started' | 'queued' | 'running' | 'completed' | 'failed' | 'ineligible'

export interface EcgMeasurement {
  id: string
  device_id: string
  duration_s: 60 | 180 | 300
  status: EcgMeasurementStatus
  created_at: number
  updated_at: number
  expires_at: number
  session_id: string | null
  message: string
  report: { model: EcgAnalysisStatus; physiology: EcgAnalysisStatus }
  report_url?: string | null
}

export interface EcgMeasurementRequest {
  device_id: string
  duration_s: 60 | 180 | 300
  request_key: string
}

export interface EcgDevices extends EcgEnvelope { devices: EcgDevice[] }
export interface EcgMeasurements extends EcgEnvelope { measurements: EcgMeasurement[] }
export interface EcgMeasurementResult extends EcgEnvelope { measurement: EcgMeasurement }

export interface EcgWeeklySummaryData {
  ecg_user: { id: string; username: string }
  expires_at: number
  week_start: string
  week_end: string
  timezone: string
  observed_days: number
  total_records: number
  total_duration_s: number
  hr_mean: number | null
  hr_records: number
  daily_series: Array<{ date: string; records: number; duration_s: number; hr_mean: number | null; hr_records: number }>
}
