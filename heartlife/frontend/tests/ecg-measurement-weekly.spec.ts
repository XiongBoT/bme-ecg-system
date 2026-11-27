import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import EcgMeasurementPanel from '../src/components/common/EcgMeasurementPanel.vue'
import EcgWeeklySummary from '../src/components/common/EcgWeeklySummary.vue'
import WeeklyReportView from '../src/views/WeeklyReportView.vue'
import { useAuthStore } from '../src/stores/auth'
import { setCsrfToken } from '../src/api/client'

function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }) }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r }); return { promise, resolve } }
const envelope = { ecg_user: { id: 'ecg-alice', username: 'alice' }, expires_at: 1893456000, measurement_allowed: true }
const devices = { ...envelope, devices: [{ device_id: 'pi-ready', label: '我的采集终端', online: true, ready: true, reason: '' }, { device_id: 'pi-offline', label: '离线终端', online: false, ready: false, reason: '设备离线' }] }
function measurement(status = 'queued') { return { id: 'measure-1', device_id: 'pi-ready', duration_s: 60, status, created_at: 1795690800, updated_at: 1795690800, expires_at: 1893456000, session_id: status === 'completed' ? 'session-a' : null, message: status === 'completed' ? '测量记录已上传' : '等待终端开始采集', report: { model: 'not_started', physiology: 'not_started' }, report_url: status === 'completed' ? 'https://ecg.example.test/?record=session-a' : null } }
function weekly(records = 2) { return { ...envelope, week_start: '2026-11-23', week_end: '2026-11-29', timezone: 'Asia/Shanghai', observed_days: 4, total_records: records, total_duration_s: 120, hr_mean: null, hr_records: 0, daily_series: [{ date: '2026-11-23', records: 0, duration_s: 0, hr_mean: null, hr_records: 0 }, { date: '2026-11-24', records: 2, duration_s: 120, hr_mean: null, hr_records: 0 }] } }
const wrappers: VueWrapper[] = []
async function mountPanel(allowed = true) {
  const wrapper = mount(EcgMeasurementPanel, { props: { measurementAllowed: allowed, ecgUrl: 'https://ecg.example.test/', connectUrl: 'https://ecg.example.test/heartlife-connect' } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function button(wrapper: VueWrapper, label: string) { const found = wrapper.findAll('button').find((x) => x.text() === label); expect(found, label).toBeDefined(); return found! }
async function chooseAndSubmit(wrapper: VueWrapper) { await wrapper.get('#ecg-measure-device').setValue('pi-ready'); await wrapper.get('form').trigger('submit') }

beforeEach(() => {
  sessionStorage.clear()
  setActivePinia(createPinia())
  setCsrfToken('measurement-csrf')
  useAuthStore().user = { id: 'hl-alice', account: 'alice', nickname: 'Alice', bio: '', timezone: 'Asia/Shanghai', roles: ['member'], is_demo: false, created_at: '2026-11-26T00:00:00Z' }
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
})
afterEach(() => { wrappers.splice(0).forEach((w) => w.unmount()); vi.useRealTimers(); vi.restoreAllMocks() })

describe('explicitly authorized ECG measurement', () => {
  it('keeps old read-only grants read-only without requesting device or measurement APIs', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    const wrapper = await mountPanel(false)
    expect(wrapper.text()).toContain('当前关联仅允许读取摘要')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('lists only returned devices and prevents selection of offline devices', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => Promise.resolve(response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] })))
    const wrapper = await mountPanel()
    expect(wrapper.get('option[value="pi-offline"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('设备离线')
    const durations = wrapper.findAll('#ecg-measure-duration option').map((x) => x.attributes('value'))
    expect(durations).toEqual(['60', '180', '300'])
  })

  it('preserves the exact request key and parameters after a lost response and prevents duplicate submissions', async () => {
    const first = deferred<Response>()
    const posts: RequestInit[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
      if (options?.method === 'POST') { posts.push(options); return posts.length === 1 ? first.promise : Promise.resolve(response({ ...envelope, measurement: measurement() }, 202)) }
      return Promise.resolve(response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] }))
    })
    const wrapper = await mountPanel()
    await chooseAndSubmit(wrapper)
    await wrapper.get('form').trigger('submit')
    expect(posts).toHaveLength(1)
    first.resolve(response({ error: { code: 'ECG_UNAVAILABLE', message: '响应丢失，请重试原请求' } }, 503))
    await flushPromises()
    expect(wrapper.get('#ecg-measure-device').attributes('disabled')).toBeDefined()
    await button(wrapper, '重试同一次测量').trigger('click')
    await flushPromises()
    expect(posts).toHaveLength(2)
    const body = JSON.parse(posts[0].body as string)
    expect(body).toMatchObject({ device_id: 'pi-ready', duration_s: 60 })
    expect(body.request_key).toMatch(/^[0-9a-f-]{36}$/)
    expect(posts[1].body).toBe(posts[0].body)
    expect(new Headers(posts[1].headers).get('X-CSRF-Token')).toBe('measurement-csrf')
  })

  it('distinguishes upload completion from report availability and does not request analysis', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url) => Promise.resolve(response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [measurement('completed')] })))
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('上传完成')
    expect(wrapper.text()).toContain('尚未分析')
    expect(wrapper.text()).not.toContain('报告已生成')
    expect(wrapper.find('a[href="https://ecg.example.test/?record=session-a"]').exists()).toBe(true)
    expect(fetchMock.mock.calls.every(([url, options]) => !String(url).includes('analysis') && options?.method !== 'POST')).toBe(true)
  })

  it('restores an uncertain request after leaving the page and retries its original key', async () => {
    const posts: RequestInit[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
      if (options?.method === 'POST') {
        posts.push(options)
        return Promise.resolve(posts.length === 1 ? response({ error: { code: 'ECG_UNAVAILABLE', message: '响应尚未确认' } }, 503) : response({ ...envelope, measurement: measurement() }))
      }
      return Promise.resolve(response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] }))
    })
    const first = await mountPanel()
    await chooseAndSubmit(first)
    await flushPromises()
    first.unmount()
    const returned = await mountPanel()
    expect(returned.get('#ecg-measure-device').attributes('disabled')).toBeDefined()
    await button(returned, '重试同一次测量').trigger('click')
    await flushPromises()
    expect(posts).toHaveLength(2)
    expect(posts[1].body).toBe(posts[0].body)
    expect(sessionStorage.getItem('heartlife:pending-ecg-measurement')).toBeNull()
  })

  it('retains the request after a malformed successful response', async () => {
    const posts: RequestInit[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
      if (options?.method === 'POST') {
        posts.push(options)
        return Promise.resolve(response(posts.length === 1 ? { ok: true } : { ...envelope, measurement: measurement() }))
      }
      return Promise.resolve(response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] }))
    })
    const wrapper = await mountPanel()
    await chooseAndSubmit(wrapper)
    await flushPromises()
    expect(wrapper.text()).toContain('尚未确认测量结果')
    await button(wrapper, '重试同一次测量').trigger('click')
    await flushPromises()
    expect(posts[1].body).toBe(posts[0].body)
  })

  it('bounds a hanging request and preserves its key on timeout', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const posts: RequestInit[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
      if (options?.method === 'POST') {
        posts.push(options)
        if (posts.length === 1) return new Promise<Response>((_resolve, reject) => options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }))
        return Promise.resolve(response({ ...envelope, measurement: measurement() }))
      }
      return Promise.resolve(response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] }))
    })
    const wrapper = await mountPanel()
    await chooseAndSubmit(wrapper)
    await vi.advanceTimersByTimeAsync(15000)
    await flushPromises()
    expect(wrapper.text()).toContain('尚未确认是否收到请求')
    await button(wrapper, '重试同一次测量').trigger('click')
    await flushPromises()
    expect(posts[1].body).toBe(posts[0].body)
  })

  it('does not reuse an uncertain request after authorization changes or logout', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => Promise.resolve(options?.method === 'POST' ? response({ error: { code: 'ECG_UNAVAILABLE', message: '未确认' } }, 503) : response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] })))
    const wrapper = await mountPanel()
    await chooseAndSubmit(wrapper)
    await flushPromises()
    expect(sessionStorage.getItem('heartlife:pending-ecg-measurement')).not.toBeNull()
    await wrapper.setProps({ authorizationExpiresAt: 1893456999 })
    await flushPromises()
    expect(sessionStorage.getItem('heartlife:pending-ecg-measurement')).toBeNull()
    expect(wrapper.text()).not.toContain('重试同一次测量')
    await chooseAndSubmit(wrapper)
    await flushPromises()
    useAuthStore().clearSession()
    expect(sessionStorage.getItem('heartlife:pending-ecg-measurement')).toBeNull()
  })

  it('polls only active work, pauses while hidden, and stops after completion', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    let active = true
    let reads = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      if (String(url).includes('/devices')) return Promise.resolve(response(devices))
      reads += 1
      return Promise.resolve(response({ ...envelope, measurements: [measurement(active ? 'recording' : 'completed')] }))
    })
    const wrapper = await mountPanel()
    const firstCount = reads
    await vi.advanceTimersByTimeAsync(4000)
    expect(reads).toBeGreaterThan(firstCount)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    const paused = reads
    await vi.advanceTimersByTimeAsync(12000)
    expect(reads).toBe(paused)
    active = false
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    const completed = reads
    await vi.advanceTimersByTimeAsync(12000)
    expect(reads).toBe(completed)
    expect(wrapper.text()).toContain('上传完成')
  })

  it('clears pending device data when the account changes and rejects old responses', async () => {
    const slow = deferred<Response>()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => String(url).includes('/devices') ? slow.promise : Promise.resolve(response({ ...envelope, measurements: [] })))
    const wrapper = await mountPanel()
    useAuthStore().clearSession()
    slow.resolve(response(devices))
    await flushPromises()
    expect(wrapper.text()).not.toContain('我的采集终端')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('stops measurement controls when permission is revoked', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(response({ error: { code: 'ECG_MEASUREMENT_FORBIDDEN', message: '测量授权已撤销' } }, 403)))
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('测量授权已撤销')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('can recheck device permission without replaying a rejected measurement', async () => {
    let revoked = true
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url) => Promise.resolve(revoked ? response({ error: { code: 'ECG_MEASUREMENT_FORBIDDEN', message: '设备权限已变化' } }, 403) : response(String(url).includes('/devices') ? devices : { ...envelope, measurements: [] })))
    const wrapper = await mountPanel()
    expect(wrapper.find('form').exists()).toBe(false)
    revoked = false
    await button(wrapper, '重新检查测量权限').trigger('click')
    await flushPromises()
    expect(wrapper.find('form').exists()).toBe(true)
    expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true)
  })
})

describe('private ECG weekly summary', () => {
  async function renderWeekly(weekStart = '2026-11-23') {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }, { path: '/ecg', component: { template: '<div />' } }] })
    await router.push('/')
    const wrapper = mount(EcgWeeklySummary, { props: { weekStart }, global: { plugins: [router] } })
    wrappers.push(wrapper)
    await flushPromises()
    return wrapper
  }
  it('uses a separate private endpoint and preserves missing heart rate', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(weekly()))
    const wrapper = await renderWeekly()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/me/ecg/weekly-summary?week_start=2026-11-23')
    expect(wrapper.text()).toContain('暂无心率数据')
    expect(wrapper.text()).toContain('仅本人可见')
    expect(wrapper.classes()).toContain('no-print')
  })

  it('ignores a previous week response after navigating to another week', async () => {
    const slow = deferred<Response>()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => String(url).includes('2026-11-23') ? slow.promise : Promise.resolve(response({ ...weekly(8), week_start: '2026-11-16', week_end: '2026-11-22' })))
    const wrapper = await renderWeekly()
    await wrapper.setProps({ weekStart: '2026-11-16' })
    await flushPromises()
    slow.resolve(response(weekly(999)))
    await flushPromises()
    expect(wrapper.text()).toContain('2026-11-16')
    expect(wrapper.text()).not.toContain('999')
  })

  it('does not block the lifestyle report when the ECG service fails', async () => {
    useAuthStore().publicConfig.ecg_integration_enabled = true
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }, { path: '/ecg', component: { template: '<div />' } }, { path: '/journal', component: { template: '<div />' } }] })
    await router.push('/')
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => Promise.resolve(String(url).includes('/ecg/') ? response({ error: { code: 'ECG_UNAVAILABLE', message: '心电服务暂不可用' } }, 503) : response({ week_start: '2026-11-23', week_end: '2026-11-29', observed_days: 4, status: 'partial_week', journal_days: 2, sleep: { mean_minutes: 480, valid_days: 2 }, activity: { total_minutes: 30, valid_days: 1 }, plans: { due: 0, completed: 0, completion_rate: null }, daily_series: [] })))
    const wrapper = mount(WeeklyReportView, { global: { plugins: [router] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.text()).toContain('480')
    expect(wrapper.text()).toContain('心电服务暂不可用')
  })
})
