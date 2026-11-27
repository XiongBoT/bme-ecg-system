import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { api, ApiClientError, setCsrfToken } from '../api/client'
import type { PublicConfig, UserProfile } from '../types/api'
import { clearPendingMeasurement } from '../utils/ecgPending'

export function sanitizeExternalHttpsUrl(raw: string | null | undefined): string | null {
  if (!raw || typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('https://')) return null
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'https:') return null
    if (parsed.username || parsed.password || parsed.search || parsed.hash) return null
    return parsed.toString()
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(null)
  watch(() => user.value?.id, (next, previous) => {
    if (previous && previous !== next) clearPendingMeasurement(previous)
  }, { flush: 'sync' })
  const initialized = ref(false)
  const configLoaded = ref(false)
  const unreadCount = ref(0)

  const publicConfig = ref<PublicConfig>({
    assistant_enabled: false,
    ecg_external_url: null,
    ecg_integration_enabled: false,
    demo_mode: false,
  })

  const isAuthenticated = computed(() => user.value !== null)
  const roles = computed(() => user.value?.roles ?? [])
  const isModerator = computed(() => roles.value.includes('moderator'))
  const isEditor = computed(() => roles.value.includes('editor'))
  const isOps = computed(() => isModerator.value || isEditor.value)

  const safeEcgExternalUrl = computed(() =>
    sanitizeExternalHttpsUrl(publicConfig.value.ecg_external_url)
  )

  async function fetchPublicConfig(): Promise<void> {
    try {
      const cfg = await api.get<PublicConfig>('/public-config')
      publicConfig.value = {
        assistant_enabled: Boolean(cfg?.assistant_enabled),
        ecg_external_url: cfg?.ecg_external_url ?? null,
        ecg_integration_enabled: Boolean(cfg?.ecg_integration_enabled),
        demo_mode: Boolean(cfg?.demo_mode),
      }
    } catch {
      // Keep safe defaults
    } finally {
      configLoaded.value = true
    }
  }

  async function fetchMe(): Promise<UserProfile | null> {
    try {
      const me = await api.get<UserProfile>('/me')
      user.value = me
      if (me.csrf_token) {
        setCsrfToken(me.csrf_token)
      }
      return me
    } catch (err) {
      if (err instanceof ApiClientError && err.status === 401) {
        user.value = null
        setCsrfToken(null)
        unreadCount.value = 0
      }
      return null
    } finally {
      initialized.value = true
    }
  }

  async function bootstrap(): Promise<void> {
    if (initialized.value && configLoaded.value) return
    await Promise.all([
      configLoaded.value ? Promise.resolve() : fetchPublicConfig(),
      initialized.value ? Promise.resolve() : fetchMe(),
    ])
    if (user.value) {
      refreshUnreadCount()
    }
  }

  async function refreshUnreadCount(): Promise<void> {
    if (!user.value) {
      unreadCount.value = 0
      return
    }
    try {
      const data = await api.get<{ items?: Array<{ read_at: string | null }>; unread_count?: number }>(
        '/me/notifications'
      )
      if (typeof data.unread_count === 'number') {
        unreadCount.value = data.unread_count
      } else if (Array.isArray(data.items)) {
        unreadCount.value = data.items.filter((n) => !n.read_at).length
      }
    } catch {
      // Ignore silent badge refresh error
    }
  }

  async function register(payload: {
    account: string
    password: string
    nickname: string
    timezone: string
  }): Promise<void> {
    await api.post('/auth/register', payload)
  }

  async function login(payload: { account: string; password: string }): Promise<UserProfile> {
    const res = await api.post<{ user: UserProfile; csrf_token: string }>('/auth/login', payload)
    setCsrfToken(res.csrf_token)
    user.value = res.user
    initialized.value = true
    refreshUnreadCount()
    return res.user
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/auth/logout')
    } catch {
      // Always clear client session
    } finally {
      user.value = null
      unreadCount.value = 0
      setCsrfToken(null)
    }
  }

  async function revokeAllSessions(): Promise<void> {
    await api.post('/me/revoke-sessions')
    user.value = null
    unreadCount.value = 0
    setCsrfToken(null)
  }

  async function updateProfile(payload: {
    nickname?: string
    bio?: string
    timezone?: string
  }): Promise<UserProfile> {
    const updated = await api.patch<UserProfile>('/me', payload)
    user.value = updated
    if (updated.csrf_token) {
      setCsrfToken(updated.csrf_token)
    }
    return updated
  }

  function clearSession(): void {
    user.value = null
    unreadCount.value = 0
    setCsrfToken(null)
  }

  return {
    user,
    initialized,
    configLoaded,
    unreadCount,
    publicConfig,
    isAuthenticated,
    roles,
    isModerator,
    isEditor,
    isOps,
    safeEcgExternalUrl,
    fetchPublicConfig,
    fetchMe,
    bootstrap,
    refreshUnreadCount,
    register,
    login,
    logout,
    revokeAllSessions,
    updateProfile,
    clearSession,
  }
})
