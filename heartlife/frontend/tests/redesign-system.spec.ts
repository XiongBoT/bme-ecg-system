import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import AppShell from '../src/components/AppShell.vue'
import DisplaySettings from '../src/components/common/DisplaySettings.vue'
import HealthMetricCard from '../src/components/common/HealthMetricCard.vue'
import HlAvatar from '../src/components/ui/HlAvatar.vue'
import { useAuthStore } from '../src/stores/auth'
import { DISPLAY_PREFS_STORAGE_KEY, usePreferencesStore } from '../src/stores/preferences'

function buildRouter(initial = '/') {
  const Dummy = { template: '<div>内容</div>' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Dummy },
      { path: '/community', component: Dummy },
      { path: '/plans', component: Dummy },
      { path: '/knowledge', component: Dummy },
      { path: '/challenges', component: Dummy },
      { path: '/assistant', component: Dummy },
      { path: '/ops', component: Dummy },
      { path: '/journal', component: Dummy },
      { path: '/notifications', component: Dummy },
      { path: '/me', component: Dummy },
      { path: '/login', component: Dummy },
    ],
  })
  router.push(initial)
  return router
}

describe('UI-01 Design System, Navigation & Elderly Display Preferences', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    delete document.documentElement.dataset.fontSize
    delete document.documentElement.dataset.contrast
    delete document.documentElement.dataset.reducedMotion
  })

  it('UI-T04: AppShell marks active desktop and mobile navigation link with aria-current="page"', async () => {
    const router = buildRouter('/community')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      account: 'demo_alice',
      nickname: '林晓禾（演示）',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: true,
      created_at: '2026-11-26T00:00:00Z',
    }

    const wrapper = mount(AppShell, {
      global: { plugins: [router] },
      slots: { default: '<div>页面内容</div>' },
    })

    const desktopCurrent = wrapper.find('nav[aria-label="主导航"] a[aria-current="page"]')
    expect(desktopCurrent.exists()).toBe(true)
    expect(desktopCurrent.text()).toContain('社区')

    const mobileCurrent = wrapper.find('nav[aria-label="底部主导航"] a[aria-current="page"]')
    expect(mobileCurrent.exists()).toBe(true)
    expect(mobileCurrent.text()).toContain('社区')
  })

  it('UI-T07 & UI-T08: DisplaySettings toggles Large Font and High Contrast, updates html dataset, persists only display settings, and restores defaults', async () => {
    const wrapper = mount(DisplaySettings)
    const prefs = usePreferencesStore()

    expect(prefs.fontSize).toBe('default')
    expect(document.documentElement.dataset.fontSize).toBeUndefined()

    // Enable Large Font
    await wrapper.find('[data-testid="pref-large-font"]').trigger('click')
    await flushPromises()
    expect(prefs.fontSize).toBe('large')
    expect(document.documentElement.dataset.fontSize).toBe('large')

    // Enable High Contrast
    await wrapper.find('[data-testid="pref-high-contrast"]').trigger('click')
    await flushPromises()
    expect(prefs.contrast).toBe('high')
    expect(document.documentElement.dataset.contrast).toBe('high')

    // Verify localStorage stores ONLY display prefs (zero health or token fields)
    const rawSaved = localStorage.getItem(DISPLAY_PREFS_STORAGE_KEY)
    expect(rawSaved).toBeTruthy()
    const parsed = JSON.parse(rawSaved!)
    expect(Object.keys(parsed).sort()).toEqual(['contrast', 'fontSize', 'reducedMotion'])

    // Simulate reload hydration in a fresh Pinia instance
    setActivePinia(createPinia())
    const rehydrated = usePreferencesStore()
    rehydrated.hydrate()
    expect(rehydrated.fontSize).toBe('large')
    expect(rehydrated.contrast).toBe('high')

    // Restore defaults
    const wrapper2 = mount(DisplaySettings)
    await wrapper2.find('[data-testid="pref-reset-defaults"]').trigger('click')
    await flushPromises()
    expect(document.documentElement.dataset.fontSize).toBeUndefined()
    expect(document.documentElement.dataset.contrast).toBeUndefined()
  })

  it('HealthMetricCard clearly shows 尚未记录 when value is null and never fabricates 0', () => {
    const missingCard = mount(HealthMetricCard, {
      props: {
        label: '今日睡眠',
        value: null,
        unit: '分钟',
        emptyText: '尚未记录',
        subtext: '记录睡眠有助于观察规律',
      },
    })
    expect(missingCard.text()).toContain('尚未记录')
    expect(missingCard.text()).not.toContain('0 分钟')

    const zeroCard = mount(HealthMetricCard, {
      props: {
        label: '今日活动',
        value: 0,
        unit: '分钟',
      },
    })
    expect(zeroCard.text()).toContain('0')
    expect(zeroCard.text()).toContain('分钟')
  })

  it('HlAvatar generates local first-character avatar deterministically without external photo URLs', () => {
    const av = mount(HlAvatar, {
      props: { name: '王秀兰（演示）', size: 'md' },
    })
    expect(av.text()).toBe('王')
    expect(av.find('img').exists()).toBe(false)
  })
})
