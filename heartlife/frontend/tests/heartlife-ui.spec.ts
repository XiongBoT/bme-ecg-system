import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import AppShell from '../src/components/AppShell.vue'
import HomeView from '../src/views/HomeView.vue'
import WeeklyReportView from '../src/views/WeeklyReportView.vue'
import JournalView from '../src/views/JournalView.vue'
import PostDetailView from '../src/views/PostDetailView.vue'
import AssistantView from '../src/views/AssistantView.vue'
import { useAuthStore } from '../src/stores/auth'
import { ApiClientError, apiRequest, setCsrfToken } from '../src/api/client'

function makeTestRouter(initialPath = '/') {
  const Dummy = { template: '<div>page</div>' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: HomeView },
      { path: '/login', component: Dummy },
      { path: '/journal', component: JournalView },
      { path: '/plans', component: Dummy },
      { path: '/community', component: Dummy },
      { path: '/community/:id', component: PostDetailView },
      { path: '/knowledge', component: Dummy },
      { path: '/knowledge/:id', component: Dummy },
      { path: '/weekly-report', component: WeeklyReportView },
      { path: '/challenges', component: Dummy },
      { path: '/assistant', component: AssistantView },
      { path: '/notifications', component: Dummy },
      { path: '/me', component: Dummy },
      { path: '/users/:id', component: Dummy },
      { path: '/ops', component: Dummy },
    ],
  })
  router.push(initialPath)
  return router
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('HeartLife Centered Frontend Suite', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setCsrfToken('test-csrf-token-123')
    vi.restoreAllMocks()
  })

  it('1. AppShell renders centered desktop pills, exact 5 mobile items, conditional Assistant/Ops, and zero sidebar', async () => {
    const router = makeTestRouter('/')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      account: 'alice',
      nickname: '林晓禾',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: true,
      created_at: '2026-11-26T00:00:00Z',
    }
    auth.publicConfig = {
      assistant_enabled: false,
      ecg_external_url: null,
      demo_mode: true,
    }
    auth.unreadCount = 3

    const wrapper = mount(AppShell, {
      global: { plugins: [router] },
      slots: { default: '<div>主内容</div>' },
    })

    // Zero left sidebar
    expect(wrapper.find('aside').exists()).toBe(false)

    // Desktop nav without assistant or ops
    const desktopLinks = wrapper
      .find('nav[aria-label="主导航"]')
      .findAll('a')
      .map((a) => a.text())
    expect(desktopLinks).toEqual(['首页', '社区', '计划', '百科', '挑战'])

    // Mobile bottom nav has exact 5 items
    const mobileLinks = wrapper
      .find('nav[aria-label="底部主导航"]')
      .findAll('a')
      .map((a) => a.text())
    expect(mobileLinks).toEqual(['首页', '社区', '计划', '百科', '我的'])

    // Unread badge + concise medical disclaimer footer
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('健康生活记录与科普参考 · 不作为医疗诊断建议')

    // Enable assistant & moderator role -> Assistant and Ops appear
    auth.publicConfig.assistant_enabled = true
    auth.user.roles = ['member', 'moderator']
    await flushPromises()

    const updatedDesktopLinks = wrapper
      .find('nav[aria-label="主导航"]')
      .findAll('a')
      .map((a) => a.text())
    expect(updatedDesktopLinks).toEqual(['首页', '社区', '计划', '百科', '挑战', '助手', '运营'])
  })

  it('2. Dashboard empty state never renders fake 0 分钟 when journal is unrecorded or null (T-0006, T-0601)', async () => {
    const router = makeTestRouter('/')
    await router.isReady()

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({
        today_date: '2026-11-26',
        plans_summary: { due_count: 0, completed_count: 0, items: [] },
        today_journal: {
          recorded: false,
          sleep_minutes: null,
          activity_minutes: null,
          mood: null,
        },
        recommended_articles: [],
        community_highlights: [],
        unread_notifications_count: 0,
      })
    )

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('未记录')
    expect(wrapper.text()).toContain('无计划')
    expect(wrapper.text()).toContain('记录今日')
    expect(wrapper.text()).not.toContain('0 分钟')
  })

  it('3. External ECG entry appears only for clean HTTPS URL and opens confirmation modal without query params (T-1001, T-1002)', async () => {
    const router = makeTestRouter('/')
    await router.isReady()
    const auth = useAuthStore()

    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve(
        jsonResponse({
          today_date: '2026-11-26',
          plans_summary: { due_count: 1, completed_count: 1, items: [] },
          today_journal: { recorded: true, sleep_minutes: 450, activity_minutes: 20, mood: 'good' },
          recommended_articles: [],
          community_highlights: [],
          unread_notifications_count: 0,
        })
      )
    )

    // Unsafe URL with query param is rejected by sanitizeExternalHttpsUrl
    auth.publicConfig.ecg_external_url = 'https://ecg.example.edu/?token=secret'
    const wrapper1 = mount(HomeView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper1.text()).not.toContain('独立心电检测')

    // Valid static HTTPS URL renders button -> opens modal with exact href & rel="noopener noreferrer"
    auth.publicConfig.ecg_external_url = 'https://ecg.example.edu/login'
    const wrapper2 = mount(HomeView, { global: { plugins: [router] } })
    await flushPromises()

    const ecgBtn = wrapper2.findAll('button').find((b) => b.text() === '独立心电检测')
    expect(ecgBtn).toBeDefined()
    await ecgBtn!.trigger('click')

    expect(wrapper2.text()).toContain('即将前往独立心电检测工具，需独立登录')
    const anchor = wrapper2.find('a[target="_blank"]')
    expect(anchor.exists()).toBe(true)
    expect(anchor.attributes('href')).toBe('https://ecg.example.edu/login')
    expect(anchor.attributes('rel')).toBe('noopener noreferrer')
  })

  it('4. WeeklyReportView renders 截至今日, 无计划, 未记录 vs 0 分钟, and accessible SVG + numeric table (T-0610)', async () => {
    const router = makeTestRouter('/weekly-report')
    await router.isReady()
    useAuthStore().user = {
      id: 'weekly-reader', account: 'alice', nickname: '林晓禾', bio: '',
      timezone: 'Asia/Shanghai', roles: ['member'], is_demo: true,
      created_at: '2026-11-26T00:00:00Z',
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({
        week_start: '2026-11-23',
        week_end: '2026-11-29',
        status: 'partial_week',
        journal_days: 1,
        observed_days: 4,
        sleep: { mean_minutes: null, valid_days: 0 },
        activity: { total_minutes: 0, valid_days: 1 },
        plans: { due: 0, completed: 0, completion_rate: null },
        daily_series: [
          {
            date: '2026-11-23',
            sleep_minutes: null,
            activity_minutes: 0,
            mood: 'neutral',
            plans_due: 0,
            plans_completed: 0,
          },
        ],
      })
    )

    const wrapper = mount(WeeklyReportView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('截至今日')
    expect(wrapper.text()).toContain('1 / 4 天')
    expect(wrapper.text()).toContain('无计划')
    expect(wrapper.text()).toContain('本周无应执行计划')
    expect(wrapper.find('svg[role="img"]').exists()).toBe(true)

    // Table shows 未记录 for null sleep and 0 分钟 for explicit 0 activity
    const rowText = wrapper.find('tbody tr').text()
    expect(rowText).toContain('未记录')
    expect(rowText).toContain('0 分钟')
    wrapper.unmount()
  })

  it('5. JournalView preserves null for blank input vs 0 for explicit zero input (T-0301)', async () => {
    const router = makeTestRouter('/journal')
    await router.isReady()

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.includes('/me/journals?')) {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      if (method === 'GET' && url.includes('/me/journals/')) {
        return Promise.resolve(
          jsonResponse({ error: { code: 'NOT_FOUND', message: '未找到' } }, 404)
        )
      }
      if (method === 'PUT' && url.includes('/me/journals/')) {
        const parsed = JSON.parse(String(init?.body || '{}'))
        return Promise.resolve(jsonResponse({ ...parsed, recorded: true }))
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(JournalView, { global: { plugins: [router] } })
    await flushPromises()

    // Leave sleep blank ('') and enter explicit '0' for activity
    const sleepEl = wrapper.find('#journal-sleep')
    const actEl = wrapper.find('#journal-activity')
    expect((sleepEl.element as HTMLInputElement).value).toBe('')

    await actEl.setValue('0')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const putCall = fetchSpy.mock.calls.find(
      ([u, opts]) => String(u).includes('/me/journals/') && opts?.method === 'PUT'
    )
    expect(putCall).toBeDefined()
    const sentPayload = JSON.parse(String(putCall![1]?.body))
    expect(sentPayload.sleep_minutes).toBeNull()
    expect(sentPayload.activity_minutes).toBe(0)
  })

  it('6. PostDetailView renders XSS payloads strictly as plain text and preserves failed comment draft', async () => {
    const router = makeTestRouter('/community/p-xss')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'viewer1',
      account: 'viewer1',
      nickname: '观察者',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: false,
      created_at: '2026-11-26T00:00:00Z',
    }

    const xssPayload = '<script>window.__pwned=true</script><img src=x onerror=alert(1)>'

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.endsWith('/posts/p-xss')) {
        return Promise.resolve(
          jsonResponse({
            id: 'p-xss',
            title: `标题 ${xssPayload}`,
            category: '日常健康',
            body: `正文段落 ${xssPayload}`,
            author: { id: 'author2', nickname: '作者' },
            created_at: '2026-11-26T08:00:00Z',
          })
        )
      }
      if (method === 'GET' && url.endsWith('/posts/p-xss/comments')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'c1',
                post_id: 'p-xss',
                parent_id: null,
                body: `评论 ${xssPayload}`,
                author: { id: 'author2', nickname: '作者' },
                created_at: '2026-11-26T08:05:00Z',
              },
            ],
          })
        )
      }
      if (method === 'POST' && url.endsWith('/posts/p-xss/comments')) {
        return Promise.resolve(
          jsonResponse(
            { error: { code: 'SERVER_BUSY', message: '服务繁忙，请稍后重试' } },
            503
          )
        )
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(PostDetailView, { global: { plugins: [router] } })
    await flushPromises()

    // Literal text is visible, zero injected <script> or <img> elements exist!
    expect(wrapper.text()).toContain(xssPayload)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)

    // Submit comment that fails -> draft text MUST remain in textarea!
    const textarea = wrapper.find('#comment-textarea')
    await textarea.setValue('我辛苦输入的百字评论不应丢失')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect((textarea.element as HTMLTextAreaElement).value).toBe('我辛苦输入的百字评论不应丢失')
    expect(wrapper.find('[role="alert"]').text()).toContain('服务繁忙')
  })

  it('7. AssistantView shows clean disabled state when off, and keeps auth checkboxes unchecked by default when on (T-0901, T-0903)', async () => {
    const router = makeTestRouter('/assistant')
    await router.isReady()
    const auth = useAuthStore()

    // Disabled by default
    auth.publicConfig.assistant_enabled = false
    const offWrapper = mount(AssistantView, { global: { plugins: [router] } })
    expect(offWrapper.text()).toContain('生活助手当前未启用')
    expect(offWrapper.find('a[href="/knowledge"]').exists()).toBe(true)

    // Enabled -> checkboxes unchecked by default
    auth.publicConfig.assistant_enabled = true
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({
        answer: '建议保持规律睡眠时间。',
        mode: 'grounded',
        citations: [{ id: 'art-1', title: '规律睡眠指南' }],
        fallback_url: '/knowledge',
      })
    )

    const onWrapper = mount(AssistantView, { global: { plugins: [router] } })
    const checkboxes = onWrapper.findAll('input[type="checkbox"]')
    expect(checkboxes).toHaveLength(2)
    expect((checkboxes[0].element as HTMLInputElement).checked).toBe(false)
    expect((checkboxes[1].element as HTMLInputElement).checked).toBe(false)

    await onWrapper.find('#assistant-query').setValue('如何改善睡眠')
    await onWrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const sentBody = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))
    expect(sentBody).toEqual({
      query: '如何改善睡眠',
      allow_weekly_report: false,
      allow_plans: false,
    })
    expect(onWrapper.text()).toContain('建议保持规律睡眠时间。')
    expect(onWrapper.text()).toContain('规律睡眠指南')
  })

  it('8. apiRequest attaches credentials include, X-CSRF-Token on mutating calls, and throws typed ApiClientError', async () => {
    setCsrfToken('csrf-abc-999')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: 'CSRF_INVALID',
            message: 'CSRF 校验失败',
            request_id: 'req-777',
          },
        },
        403
      )
    )

    await expect(apiRequest('/me', { method: 'PATCH', body: { nickname: '新名字' } })).rejects.toMatchObject({
      name: 'ApiClientError',
      status: 403,
      code: 'CSRF_INVALID',
      message: 'CSRF 校验失败',
      requestId: 'req-777',
    } satisfies Partial<ApiClientError>)

    const [, init] = fetchSpy.mock.calls[0]
    expect(init?.credentials).toBe('include')
    const headers = init?.headers as Headers
    expect(headers.get('X-CSRF-Token')).toBe('csrf-abc-999')
  })
})
