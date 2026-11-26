import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type FontSizeMode = 'default' | 'large'
export type ContrastMode = 'default' | 'high'

export interface DisplayPreferencesState {
  fontSize: FontSizeMode
  contrast: ContrastMode
  reducedMotion: boolean
}

export const DISPLAY_PREFS_STORAGE_KEY = 'heartlife_display_prefs'

function readStoredPrefs(): DisplayPreferencesState {
  const fallback: DisplayPreferencesState = {
    fontSize: 'default',
    contrast: 'default',
    reducedMotion: false,
  }
  if (typeof window === 'undefined' || !window.localStorage) return fallback
  try {
    const raw = window.localStorage.getItem(DISPLAY_PREFS_STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<DisplayPreferencesState>
    return {
      fontSize: parsed.fontSize === 'large' ? 'large' : 'default',
      contrast: parsed.contrast === 'high' ? 'high' : 'default',
      reducedMotion: Boolean(parsed.reducedMotion),
    }
  } catch {
    return fallback
  }
}

export function applyPrefsToDocument(prefs: DisplayPreferencesState): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (prefs.fontSize === 'large') {
    root.dataset.fontSize = 'large'
  } else {
    delete root.dataset.fontSize
  }

  if (prefs.contrast === 'high') {
    root.dataset.contrast = 'high'
  } else {
    delete root.dataset.contrast
  }

  if (prefs.reducedMotion) {
    root.dataset.reducedMotion = 'true'
  } else {
    delete root.dataset.reducedMotion
  }
}

export const usePreferencesStore = defineStore('preferences', () => {
  const initial = readStoredPrefs()
  const fontSize = ref<FontSizeMode>(initial.fontSize)
  const contrast = ref<ContrastMode>(initial.contrast)
  const reducedMotion = ref<boolean>(initial.reducedMotion)

  function syncAndPersist(): void {
    const snapshot: DisplayPreferencesState = {
      fontSize: fontSize.value,
      contrast: contrast.value,
      reducedMotion: reducedMotion.value,
    }
    applyPrefsToDocument(snapshot)
    if (typeof window !== 'undefined' && window.localStorage) {
      try {
        window.localStorage.setItem(DISPLAY_PREFS_STORAGE_KEY, JSON.stringify(snapshot))
      } catch {
        // Ignore storage quota errors
      }
    }
  }

  function setFontSize(next: FontSizeMode): void {
    fontSize.value = next
    syncAndPersist()
  }

  function toggleFontSize(): void {
    setFontSize(fontSize.value === 'large' ? 'default' : 'large')
  }

  function setContrast(next: ContrastMode): void {
    contrast.value = next
    syncAndPersist()
  }

  function toggleContrast(): void {
    setContrast(contrast.value === 'high' ? 'default' : 'high')
  }

  function setReducedMotion(next: boolean): void {
    reducedMotion.value = next
    syncAndPersist()
  }

  function resetDefaults(): void {
    fontSize.value = 'default'
    contrast.value = 'default'
    reducedMotion.value = false
    syncAndPersist()
  }

  function hydrate(): void {
    const stored = readStoredPrefs()
    fontSize.value = stored.fontSize
    contrast.value = stored.contrast
    reducedMotion.value = stored.reducedMotion
    applyPrefsToDocument(stored)
  }

  watch([fontSize, contrast, reducedMotion], () => {
    syncAndPersist()
  })

  // Immediately sync on store creation
  applyPrefsToDocument(initial)

  return {
    fontSize,
    contrast,
    reducedMotion,
    setFontSize,
    toggleFontSize,
    setContrast,
    toggleContrast,
    setReducedMotion,
    resetDefaults,
    hydrate,
  }
})
