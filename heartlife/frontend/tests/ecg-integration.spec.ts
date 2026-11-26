import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import EcgView from '../src/views/EcgView.vue'
import EcgTrend from '../src/components/common/EcgTrend.vue'
import ConfirmDialog from '../src/components/common/ConfirmDialog.vue'
import { useAuthStore } from '../src/stores/auth'
import { buildApiUrl, setCsrfToken } from '../src/api/client'
import type { EcgLink, EcgSummary } from '../src/types/ecg'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}
const unlinked: EcgLink = { enabled: true, linked: false, ecg_username: null, expires_at: null, ecg_url: 'https://ecg.example.test/', revocation_pending: false }
const linked: EcgLink = { ...unlinked, linked: true, ecg_username: 'ecg_alice', expires_at: 1893456000 }
function summary(id = 'record-a'): EcgSummary {
  return {
    ecg_user: { id: 'ecg-user-a', username: 'ecg_alice' }, expires_at: 1893456000,
    recent_records: [{ session_id: id, started_utc: '2026-11-26T08:00:00Z', duration_s: 60, hr_mean: null, report_url: `https://ecg.example.test/?record=${id}` }],
    trends: { period: 'day', anchor: '2026-11-26', utc_offset_minutes: 480, total_records: 1, total_duration_s: 60, note: '心率来自终端质量合格窗口，缺失不记为0。', buckets: [
      { index: 0, label: '00:00', records: 0, duration_s: 0, hr_mean: null, hr_records: 0 },
      { index: 1, label: '01:00', records: 1, duration_s: 60, hr_mean: 74, hr_records: 1 },
      { index: 2, label: '02:00', records: 0, duration_s: 0, hr_mean: null, hr_records: 0 },
      { index: 3, label: '03:00', records: 1, duration_s: 60, hr_mean: 76, hr_records: 1 },
    ] },
  }
}
const wrappers: VueWrapper[] = []
async function render() {
  const Dummy = { template: '<div />' }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: Dummy }, { path: '/ecg', component: EcgView }] })
  await router.push('/ecg')
  await router.isReady()
  const wrapper = mount(EcgView, { global: { plugins: [router] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('button').find((b) => b.text() === label)
  expect(found, `button ${label}`).toBeDefined()
  return found!
}

describe('HeartLife ECG account integration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setCsrfToken('hl-test-csrf')
    useAuthStore().user = { id: 'hl-user-a', account: 'alice', nickname: 'Alice', bio: '', timezone: 'Asia/Shanghai', roles: ['member'], is_demo: false, created_at: '2026-11-26T00:00:00Z' }
    vi.restoreAllMocks()
  })
  afterEach(() => { wrappers.splice(0).forEach((w) => w.unmount()); vi.restoreAllMocks() })

  it('keeps the independent ECG entry when integration is disabled', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ ...unlinked, enabled: false }))
    const wrapper = await render()
    expect(wrapper.text()).toContain('心电摘要尚未开放')
    expect(wrapper.find('#ecg-link-code').exists()).toBe(false)
    expect(wrapper.get('a[href="https://ecg.example.test/"]').attributes('rel')).toBe('noopener noreferrer')
  })

  it('requires explicit consent and sends only a code with CSRF, clearing it after binding', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, options) => {
      if (options?.method === 'POST') return Promise.resolve(json(linked))
      return Promise.resolve(json(String(input).includes('/summary') ? summary() : unlinked))
    })
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = await render()
    expect(wrapper.find('a[href="https://ecg.example.test/heartlife-connect"]').exists()).toBe(true)
    await wrapper.get('#ecg-link-code').setValue('test-onetime-code-abcdefghijklmnopqrstuvwxyz')
    expect(button(wrapper, '确认关联').attributes('disabled')).toBeDefined()
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const post = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST')!
    expect(post[0]).toBe('/api/v1/me/ecg/link')
    expect(JSON.parse(post[1]!.body as string)).toEqual({ code: 'test-onetime-code-abcdefghijklmnopqrstuvwxyz' })
    expect(new Headers(post[1]!.headers).get('X-CSRF-Token')).toBe('hl-test-csrf')
    expect(wrapper.text()).toContain('心电账号：ecg_alice')
    expect(wrapper.find('#ecg-link-code').exists()).toBe(false)
    expect(storage).not.toHaveBeenCalled()
  })

  it('shows missing heart rate as unavailable and preserves gaps in the plotted series', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => Promise.resolve(json(String(input).includes('/summary') ? summary() : linked)))
    const wrapper = await render()
    expect(wrapper.text()).toContain('暂无心率数据')
    expect(wrapper.getComponent(EcgTrend).findAll('polyline')).toHaveLength(2)
    const rows = wrapper.getComponent(EcgTrend).findAll('tbody tr')
    expect(rows[0].text()).toContain('暂无数据')
    expect(rows[0].findAll('td')[0].text()).toBe('0')
    expect(wrapper.get('a[href="https://ecg.example.test/?record=record-a"]').text()).toBe('查看记录与报告')
  })

  it('rechecks the persisted status after an uncertain binding response before allowing another attempt', async () => {
    let readCount = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, options) => {
      if (options?.method === 'POST') return Promise.resolve(json({ error: { code: 'ECG_UNAVAILABLE', message: '授权状态待确认' } }, 503))
      readCount += 1
      return Promise.resolve(json(readCount === 1 ? unlinked : { ...unlinked, revocation_pending: true }))
    })
    const wrapper = await render()
    await wrapper.get('#ecg-link-code').setValue('uncertain-one-time-code')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('授权状态待确认')
    expect(wrapper.find('#ecg-link-code').exists()).toBe(false)
    expect(button(wrapper, '重试撤销')).toBeDefined()
  })

  it('discards an older period response even when the transport ignores abort', async () => {
    const slow = deferred<Response>()
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (!url.includes('/summary')) return Promise.resolve(json(linked))
      if (url.includes('period=month')) return slow.promise
      return Promise.resolve(json(summary(url.includes('period=year') ? 'new-year-result' : 'initial-result')))
    })
    const wrapper = await render()
    await button(wrapper, '月').trigger('click')
    await button(wrapper, '年').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('new-year-result')
    slow.resolve(json(summary('old-month-result')))
    await flushPromises()
    expect(wrapper.text()).not.toContain('old-month-result')
    expect(wrapper.text()).toContain('new-year-result')
  })

  it('clears private results on logout and rejects the delayed response', async () => {
    const slow = deferred<Response>()
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => String(input).includes('/summary') ? slow.promise : Promise.resolve(json(linked)))
    const wrapper = await render()
    useAuthStore().clearSession()
    slow.resolve(json(summary('previous-user-record')))
    await flushPromises()
    expect(wrapper.text()).not.toContain('previous-user-record')
    expect(wrapper.text()).not.toContain('ecg_alice')
  })

  it('replaces an old account view immediately and rejects its late mutation response', async () => {
    const slow = deferred<Response>()
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, options) => options?.method === 'POST' ? slow.promise : Promise.resolve(json(unlinked)))
    const wrapper = await render()
    await wrapper.get('#ecg-link-code').setValue('code-for-alice')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    useAuthStore().user = { ...useAuthStore().user!, id: 'hl-user-b', account: 'bob' }
    await flushPromises()
    slow.resolve(json(linked))
    await flushPromises()
    expect(wrapper.text()).not.toContain('ecg_alice')
    expect((wrapper.get('#ecg-link-code').element as HTMLInputElement).value).toBe('')
  })

  it('hides late summaries during revoke and offers retry when the remote revoke is pending', async () => {
    const slow = deferred<Response>()
    let summaryCalls = 0
    let deleteCalls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, options) => {
      if (options?.method === 'DELETE') {
        deleteCalls += 1
        return Promise.resolve(json({ linked: false, revocation_pending: deleteCalls === 1 }))
      }
      if (String(input).includes('/summary')) return ++summaryCalls === 1 ? Promise.resolve(json(summary())) : slow.promise
      return Promise.resolve(json(linked))
    })
    const wrapper = await render()
    await button(wrapper, '刷新摘要').trigger('click')
    await button(wrapper, '解除关联').trigger('click')
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm')
    await flushPromises()
    slow.resolve(json(summary('delayed-after-revoke')))
    await flushPromises()
    expect(wrapper.text()).toContain('授权状态待确认')
    expect(wrapper.text()).not.toContain('delayed-after-revoke')
    expect(wrapper.find('#ecg-link-code').exists()).toBe(false)
    await button(wrapper, '重试撤销').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已解除关联')
    expect(wrapper.find('#ecg-link-code').exists()).toBe(true)
  })

  it('clears old data on a failed refresh without signing the HeartLife user out', async () => {
    let count = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (!String(input).includes('/summary')) return Promise.resolve(json(linked))
      return Promise.resolve(++count === 1 ? json(summary('old-readable-record')) : json({ error: { code: 'ECG_UNAVAILABLE', message: '心电服务暂不可用' } }, 503))
    })
    const wrapper = await render()
    expect(wrapper.text()).toContain('old-readable-record')
    await button(wrapper, '刷新摘要').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('old-readable-record')
    expect(wrapper.text()).toContain('心电服务暂不可用')
    expect(useAuthStore().user?.id).toBe('hl-user-a')
  })

  it('never renders a report link outside the configured ECG origin', async () => {
    const data = summary()
    data.recent_records[0].report_url = 'https://untrusted.example.test/?record=record-a'
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => Promise.resolve(json(String(input).includes('/summary') ? data : linked)))
    const wrapper = await render()
    expect(wrapper.find('a[href^="https://untrusted"]').exists()).toBe(false)
  })
})

describe('HeartLife API mount path', () => {
  it('addresses only HeartLife API routes on root and subpath deployments', () => {
    expect(buildApiUrl('/me/ecg/link', undefined, '/')).toBe('/api/v1/me/ecg/link')
    expect(buildApiUrl('/me/ecg/summary', { period: 'month', anchor: '2026-11-26' }, '/heartlife/')).toBe('/heartlife/api/v1/me/ecg/summary?period=month&anchor=2026-11-26')
    expect(buildApiUrl('/api/v1/me', undefined, '/heartlife/')).toBe('/heartlife/api/v1/me')
    expect(buildApiUrl('/heartlife/api/v1/me', undefined, '/heartlife/')).toBe('/heartlife/api/v1/me')
  })
})
