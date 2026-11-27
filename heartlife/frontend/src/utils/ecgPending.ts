import type { EcgMeasurementRequest } from '../types/ecg'

const storageKey = 'heartlife:pending-ecg-measurement'
type Pending = { userId: string; authorization: number | null; request: EcgMeasurementRequest }

export function clearPendingMeasurement(userId?: string) {
  try {
    if (userId) {
      const raw = sessionStorage.getItem(storageKey)
      if (raw && (JSON.parse(raw) as Pending).userId !== userId) return
    }
    sessionStorage.removeItem(storageKey)
  } catch { /* Browser storage can be disabled; the component also clears memory. */ }
}

export function savePendingMeasurement(userId: string, authorization: number | null, request: EcgMeasurementRequest) {
  try { sessionStorage.setItem(storageKey, JSON.stringify({ userId, authorization, request })); return true }
  catch { return false }
}

export function readPendingMeasurement(userId: string, authorization: number | null): EcgMeasurementRequest | null {
  try {
    const raw = sessionStorage.getItem(storageKey)
    if (!raw) return null
    const value = JSON.parse(raw) as Pending
    const request = value.request
    if (value.userId !== userId || value.authorization !== authorization || !request ||
      !/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(request.device_id) ||
      ![60, 180, 300].includes(request.duration_s) || !/^[a-f0-9-]{32,36}$/.test(request.request_key)) {
      clearPendingMeasurement()
      return null
    }
    return { device_id: request.device_id, duration_s: request.duration_s, request_key: request.request_key }
  } catch { clearPendingMeasurement(); return null }
}
