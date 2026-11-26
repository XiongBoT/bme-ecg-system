import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import HomeView from '../src/views/HomeView.vue'
import JournalView from '../src/views/JournalView.vue'
import PlansView from '../src/views/PlansView.vue'
import { useAuthStore } from '../src/stores/auth'
import { setCsrfToken } from '../src/api/client'

function makeTestRouter(initialPath = '/') {
  const Dummy = { template: '<div>page</div>' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: HomeView },
      { path: '/login', component: Dummy },
      { path: '/journal', component: JournalView },
      { path: '/plans', component: PlansView },
      { path: '/community', component: Dummy },
      { path: '/community/:id', component: Dummy },
      { path: '/knowledge', component: Dummy },
      { path: '/knowledge/:id', component: Dummy },
      { path: '/weekly-report', component: Dummy },
      { path: '/challenges', component: Dummy },
      { path: '/assistant', component: Dummy },
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

describe('UI-03 Warm Companion Home, Journal & Habit Plans Suite', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setCsrfToken('ui03-csrf-token')
    vi.restoreAllMocks()
  })

  it('UI-T18 & UI-T31: HomeView renders warm companion hero, decorative illustration, 尚未记录 for missing metrics (never 0 分钟), zero fake health scores, and conditional assistant/ECG entries', async () => {
    const router = makeTestRouter('/')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'u-home-1',
      account: 'alice',
      nickname: '林晓禾',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: false,
      created_at: '2026-11-26T00:00:00Z',
    }
    auth.publicConfig = {
      assistant_enabled: false,
      ecg_external_url: null,
      demo_mode: false,
    }

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
        recommended_articles: [
          {
            id: 'art-1',
            title: '秋冬季规律散步小贴士',
            summary: '循序渐进活动身体',
            category: '运动与习惯',
          },
        ],
        community_highlights: [
          {
            id: 'post-1',
            title: '每天晚饭后散步二十分钟',
            category: '日常健康',
            author: { id: 'u2', nickname: '周大叔' },
            created_at: '2026-11-26T08:00:00Z',
          },
        ],
        unread_notifications_count: 2,
      })
    )

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    const text = wrapper.text()

    // Warm time-aware greeting + companion copy
    expect(text).toMatch(/(早上好|下午好|晚上好)，林晓禾/)
    expect(text).toContain('慢慢来，把今天的小事照顾好，就是很棒的一天。')

    // Decorative local SVG illustration with alt="" and aria-hidden="true"
    const heroImg = wrapper.find('img.hl-hero-illustration')
    expect(heroImg.exists()).toBe(true)
    expect(heroImg.attributes('alt')).toBe('')
    expect(heroImg.attributes('aria-hidden')).toBe('true')

    // Missing health metrics show 尚未记录 (never 0 分钟)
    expect(text).toContain('尚未记录')
    expect(text).not.toContain('0 分钟')

    // Strictly zero fabricated scores
    expect(text).not.toContain('健康总分')
    expect(text).not.toContain('心脏年龄')
    expect(text).not.toContain('疾病风险')

    // Empty plan state shows 无计划 and warm creation CTA
    expect(text).toContain('无计划')
    expect(text).toContain('去创建习惯计划')

    // Optional entries hidden when disabled
    expect(text).not.toContain('独立心电检测')
    expect(wrapper.find('a[href="/assistant"]').exists()).toBe(false)

    // Enable assistant -> FeatureTile link appears
    auth.publicConfig.assistant_enabled = true
    await flushPromises()
    expect(wrapper.find('a[href="/assistant"]').exists()).toBe(true)
  })

  it('UI-T20 (HomeView): HomeView check-in API failure preserves uncompleted state and shows alert', async () => {
    const router = makeTestRouter('/')
    await router.isReady()

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.includes('/me/dashboard')) {
        return Promise.resolve(
          jsonResponse({
            today_date: '2026-11-26',
            plans_summary: {
              due_count: 1,
              completed_count: 0,
              items: [
                {
                  plan_id: 'plan-1',
                  title: '晨起温水一杯',
                  completed: false,
                  streak_days: 5,
                },
              ],
            },
            today_journal: {
              recorded: true,
              sleep_minutes: 0,
              activity_minutes: null,
              mood: 'good',
            },
            recommended_articles: [],
            community_highlights: [],
            unread_notifications_count: 0,
          })
        )
      }
      if (method === 'PUT' && url.includes('/me/plans/plan-1/checkins/2026-11-26')) {
        return Promise.resolve(
          jsonResponse({ error: { code: 'INTERNAL_ERROR', message: '服务暂时不可用，请重试' } }, 500)
        )
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(HomeView, { global: { plugins: [router] } })
    await flushPromises()

    // Explicit 0 sleep renders 0 分钟 while null activity renders 尚未记录
    expect(wrapper.text()).toContain('0')
    expect(wrapper.text()).toContain('分钟')
    expect(wrapper.text()).toContain('尚未记录')
    expect(wrapper.text()).toContain('0 / 1')

    const checkinBtn = wrapper.findAll('button').find((b) => b.text().includes('完成打卡'))
    expect(checkinBtn).toBeDefined()
    await checkinBtn!.trigger('click')
    await flushPromises()

    // Must remain 0 / 1 and uncompleted, with role="alert"
    expect(wrapper.text()).toContain('0 / 1')
    expect(wrapper.findAll('button').some((b) => b.text().includes('完成打卡'))).toBe(true)
    expect(wrapper.find('[role="alert"]').text()).toContain('服务暂时不可用')
  })

  it('UI-T19 & Two-step Delete Confirmation: JournalView shows warm unrecorded prompt on 404, preserves null vs 0, and requires ConfirmDialog before DELETE', async () => {
    const router = makeTestRouter('/journal')
    await router.isReady()

    let savedRecord: Record<string, unknown> | null = null
    let deleteCallCount = 0

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()

      if (method === 'GET' && url.includes('/me/journals?')) {
        return Promise.resolve(
          jsonResponse({
            items: savedRecord ? [savedRecord] : [],
          })
        )
      }
      if (method === 'GET' && url.includes('/me/journals/')) {
        if (savedRecord) {
          return Promise.resolve(jsonResponse(savedRecord))
        }
        return Promise.resolve(
          jsonResponse({ error: { code: 'NOT_FOUND', message: '未找到记录' } }, 404)
        )
      }
      if (method === 'PUT' && url.includes('/me/journals/')) {
        const body = JSON.parse(String(init?.body || '{}'))
        const datePart = url.split('/me/journals/')[1]?.split('?')[0] || '2026-11-26'
        savedRecord = {
          ...body,
          local_date: datePart,
          recorded: true,
        }
        return Promise.resolve(jsonResponse(savedRecord))
      }
      if (method === 'DELETE' && url.includes('/me/journals/')) {
        deleteCallCount += 1
        savedRecord = null
        return Promise.resolve(jsonResponse({ ok: true }))
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(JournalView, { global: { plugins: [router] } })
    await flushPromises()

    // 1. Unrecorded day shows warm calm prompt card & illustration
    expect(wrapper.text()).toContain('这一天还没有记录')
    expect(wrapper.text()).toContain('今天还可以记录一次')
    const calmImg = wrapper.find('img.hl-journal-calm-img')
    expect(calmImg.exists()).toBe(true)
    expect(calmImg.attributes('alt')).toBe('')
    expect(calmImg.attributes('aria-hidden')).toBe('true')

    // 2. Blank sleep ('') -> null, explicit '0' activity -> 0
    await wrapper.find('#journal-activity').setValue('0')
    await wrapper.find('#journal-note').setValue('今天在家静养读书')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const putCall = fetchSpy.mock.calls.find(
      ([u, opts]) => String(u).includes('/me/journals/') && opts?.method === 'PUT'
    )
    expect(putCall).toBeDefined()
    const payload = JSON.parse(String(putCall![1]?.body))
    expect(payload.sleep_minutes).toBeNull()
    expect(payload.activity_minutes).toBe(0)
    expect(wrapper.text()).toContain('已保存')

    // 3. Two-step delete confirmation: clicking 删除当日记录 opens ConfirmDialog; clicking 保留记录 cancels without DELETE
    const deleteTrigger = wrapper.findAll('button').find((b) => b.text().includes('删除当日记录'))
    expect(deleteTrigger).toBeDefined()
    await deleteTrigger!.trigger('click')
    await flushPromises()

    expect(deleteCallCount).toBe(0)
    expect(wrapper.text()).toContain('确认删除当日记录')
    const cancelBtn = wrapper.findAll('button').find((b) => b.text().includes('保留记录'))
    expect(cancelBtn).toBeDefined()
    await cancelBtn!.trigger('click')
    await flushPromises()

    expect(deleteCallCount).toBe(0)
    expect((wrapper.find('#journal-note').element as HTMLTextAreaElement).value).toBe(
      '今天在家静养读书'
    )

    // 4. Confirming delete fires DELETE and restores unrecorded prompt
    await deleteTrigger!.trigger('click')
    await flushPromises()
    const confirmBtn = wrapper.findAll('button').find((b) => b.text() === '确认删除')
    expect(confirmBtn).toBeDefined()
    await confirmBtn!.trigger('click')
    await flushPromises()

    expect(deleteCallCount).toBe(1)
    expect(wrapper.text()).toContain('这一天还没有记录')
  })

  it('UI-T20 (PlansView): PlansView check-in 500 error preserves uncompleted state & streak and displays role="alert"', async () => {
    const router = makeTestRouter('/plans')
    await router.isReady()

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()

      if (method === 'GET' && url.includes('/me/today')) {
        return Promise.resolve(
          jsonResponse({
            today_date: '2026-11-26',
            items: [
              {
                plan_id: 'p-walk',
                title: '晚饭后散步 20 分钟',
                completed: false,
                streak_days: 3,
                reminder_enabled: true,
                reminder_time: '19:30',
              },
            ],
          })
        )
      }
      if (method === 'GET' && url.includes('/plan-templates')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                key: 'walk_habit',
                title: '晚饭后散步 20 分钟',
                weekdays: [1, 2, 3, 4, 5, 6, 7],
                reminder_time: '19:30',
              },
            ],
          })
        )
      }
      if (method === 'GET' && url.includes('/me/plans')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'p-walk',
                title: '晚饭后散步 20 分钟',
                active: true,
                weekdays: [1, 2, 3, 4, 5, 6, 7],
                reminder_enabled: true,
                reminder_time: '19:30',
                streak_days: 3,
              },
            ],
          })
        )
      }
      if (method === 'PUT' && url.includes('/me/plans/p-walk/checkins/2026-11-26')) {
        return Promise.resolve(
          jsonResponse({ error: { code: 'DB_BUSY', message: '打卡保存失败，请稍后重试' } }, 500)
        )
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(PlansView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('把散步、饮水、规律作息变成每天轻松完成的小目标。')
    expect(wrapper.text()).toContain('0 / 1')
    expect(wrapper.text()).toContain('连续 3 天')

    const checkinBtn = wrapper.findAll('button').find((b) => b.text() === '完成打卡')
    expect(checkinBtn).toBeDefined()
    await checkinBtn!.trigger('click')
    await flushPromises()

    // Must NOT flip to 撤销打卡 or 1 / 1 or 连续 4 天 on 500 error!
    expect(wrapper.text()).toContain('0 / 1')
    expect(wrapper.text()).toContain('连续 3 天')
    expect(wrapper.text()).not.toContain('连续 4 天')
    expect(wrapper.findAll('button').some((b) => b.text() === '完成打卡')).toBe(true)
    expect(wrapper.findAll('button').some((b) => b.text() === '撤销打卡')).toBe(false)

    const alertEl = wrapper.find('[role="alert"]')
    expect(alertEl.exists()).toBe(true)
    expect(alertEl.text()).toContain('打卡保存失败，请稍后重试')
  })
})
