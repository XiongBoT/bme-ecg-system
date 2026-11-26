export class ApiClientError extends Error {
  public readonly status: number
  public readonly code: string
  public readonly requestId?: string

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

let memoryCsrfToken: string | null = null

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined' || !document.cookie) return null
  const parts = document.cookie.split(';')
  for (const part of parts) {
    const trimmed = part.trim()
    if (trimmed.startsWith(`${name}=`)) {
      return decodeURIComponent(trimmed.slice(name.length + 1))
    }
  }
  return null
}

export function setCsrfToken(token: string | null | undefined): void {
  memoryCsrfToken = token ? token.trim() : null
}

export function getCsrfToken(): string | null {
  return memoryCsrfToken || readCookie('hl_csrf')
}

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  params?: Record<string, string | number | boolean | null | undefined>
}

export function buildApiUrl(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
  basePath = import.meta.env.BASE_URL
): string {
  const base = `/${(basePath || '/').replace(/^\/+|\/+$/g, '')}`.replace(/\/$/, '')
  const relative = base && path.startsWith(`${base}/api/`) ? path.slice(base.length) : path
  const normalized = relative.startsWith('/api/')
    ? relative
    : `/api/v1${relative.startsWith('/') ? relative : `/${relative}`}`
  const url = `${base}${normalized}`
  if (!params) return url
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      usp.set(k, String(v))
    }
  }
  const qs = usp.toString()
  return qs ? `${url}?${qs}` : url
}

export async function apiRequest<T = unknown>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const { body, params, headers: customHeaders, method: rawMethod, ...rest } = options
  const method = (rawMethod || 'GET').toUpperCase()
  const url = buildApiUrl(path, params)

  const headers = new Headers(customHeaders || {})
  if (body !== undefined && !(body instanceof FormData)) {
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
  }

  if (MUTATING_METHODS.has(method)) {
    const csrf = getCsrfToken()
    if (csrf && !headers.has('X-CSRF-Token')) {
      headers.set('X-CSRF-Token', csrf)
    }
  }

  const response = await fetch(url, {
    ...rest,
    method,
    headers,
    credentials: 'include',
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  })

  const contentType = response.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')

  if (!response.ok) {
    let code = `HTTP_${response.status}`
    let message = '请求处理失败，请稍后重试'
    let requestId: string | undefined

    if (isJson) {
      try {
        const errBody = await response.json()
        if (errBody?.error && typeof errBody.error === 'object') {
          code = String(errBody.error.code || code)
          message = String(errBody.error.message || message)
          requestId = errBody.error.request_id ? String(errBody.error.request_id) : undefined
        } else if (Array.isArray(errBody?.detail) && errBody.detail.length > 0) {
          code = 'VALIDATION_ERROR'
          message = String(errBody.detail[0]?.msg || message)
        } else if (typeof errBody?.detail === 'string') {
          message = errBody.detail
        }
      } catch {
        // Keep fallback message
      }
    }
    throw new ApiClientError(response.status, code, message, requestId)
  }

  if (response.status === 204) {
    return undefined as T
  }

  if (isJson) {
    const data = await response.json()
    if (data && typeof data === 'object' && 'csrf_token' in data && typeof data.csrf_token === 'string') {
      setCsrfToken(data.csrf_token)
    }
    return data as T
  }

  return (await response.text()) as unknown as T
}

export const api = {
  get: <T = unknown>(
    path: string,
    params?: Record<string, string | number | boolean | null | undefined>
  ) => apiRequest<T>(path, { method: 'GET', params }),
  post: <T = unknown>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'POST', body }),
  put: <T = unknown>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'PUT', body }),
  patch: <T = unknown>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'PATCH', body }),
  delete: <T = unknown>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'DELETE', body }),
}

export async function toggleBookmarkApi(
  targetType: 'post' | 'article',
  targetId: string,
  shouldBookmark: boolean
): Promise<boolean> {
  const method = shouldBookmark ? 'PUT' : 'DELETE'
  const primaryPath = `/bookmarks/${targetType}/${targetId}`
  const fallbackPath = `/${targetType}s/${targetId}/bookmark`
  try {
    const res = await apiRequest<{ bookmarked?: boolean }>(primaryPath, { method })
    return res?.bookmarked ?? shouldBookmark
  } catch (err) {
    if (err instanceof ApiClientError && (err.status === 404 || err.status === 405)) {
      const res = await apiRequest<{ bookmarked?: boolean }>(fallbackPath, { method })
      return res?.bookmarked ?? shouldBookmark
    }
    throw err
  }
}
