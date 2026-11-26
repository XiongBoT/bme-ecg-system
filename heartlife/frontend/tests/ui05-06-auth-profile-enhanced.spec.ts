import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import AuthView from '../src/views/AuthView.vue'
import ProfileView from '../src/views/ProfileView.vue'
import NotificationsView from '../src/views/NotificationsView.vue'
import PublicUserView from '../src/views/PublicUserView.vue'
import OpsView from '../src/views/OpsView.vue'
import ChallengesView from '../src/views/ChallengesView.vue'
import AssistantView from '../src/views/AssistantView.vue'
import { useAuthStore } from '../src/stores/auth'
import { setCsrfToken } from '../src/api/client'

function makeRouter(initialPath = '/login') {
  const Dummy = { template: '<div>stub-page</div>' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Dummy },
      { path: '/login', component: AuthView },
      { path: '/journal', component: Dummy },
      { path: '/plans', component: Dummy },
      { path: '/me', component: ProfileView },
      { path: '/notifications', component: NotificationsView },
      { path: '/challenges', component: ChallengesView },
      { path: '/assistant', component: AssistantView },
      { path: '/community', component: Dummy },
      { path: '/community/:id', component: Dummy },
      { path: '/knowledge', component: Dummy },
      { path: '/knowledge/:id', component: Dummy },
      { path: '/users/:id', component: PublicUserView },
      { path: '/ops', component: OpsView },
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

describe('UI-05 & UI-06 Enhanced Accessibility & Warm Redesign Suite', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setCsrfToken('test-csrf-ui05-06')
    vi.restoreAllMocks()
  })

  it('1. AuthView provides >=48px accessible password show/hide toggle and conditional demo quick-fill', async () => {
    const router = makeRouter('/login')
    await router.isReady()
    const auth = useAuthStore()
    auth.publicConfig.demo_mode = false

    const wrapper = mount(AuthView, { global: { plugins: [router] } })

    // Reassuring brand header + decorative welcome illustration
    expect(wrapper.text()).toContain('欢迎来到心伴 HeartLife')
    expect(wrapper.text()).toContain('健康生活记录与科普参考 · 不作为医疗诊断建议')

    // Demo helper hidden when demo_mode is false
    expect(wrapper.text()).not.toContain('demo_alice')

    // Password toggle button: aria-pressed="false" -> "true" and type="password" -> "text"
    const pwdInput = wrapper.find('#auth-password')
    expect(pwdInput.attributes('type')).toBe('password')

    const toggleBtn = wrapper.find('button[data-testid="auth-password-toggle"]')
    expect(toggleBtn.exists()).toBe(true)
    expect(toggleBtn.attributes('aria-pressed')).toBe('false')
    expect(toggleBtn.attributes('aria-label')).toBe('显示密码')
    expect(toggleBtn.text()).toContain('显示')

    await toggleBtn.trigger('click')
    expect(toggleBtn.attributes('aria-pressed')).toBe('true')
    expect(toggleBtn.attributes('aria-label')).toBe('隐藏密码')
    expect(toggleBtn.text()).toContain('隐藏')
    expect(wrapper.find('#auth-password').attributes('type')).toBe('text')

    // Enable demo_mode -> demo quick-fill appears and populates account & password
    auth.publicConfig.demo_mode = true
    await flushPromises()
    const demoBtn = wrapper.findAll('button').find((b) => b.text().includes('demo_alice'))
    expect(demoBtn).toBeDefined()
    await demoBtn!.trigger('click')
    expect((wrapper.find('#auth-account').element as HTMLInputElement).value).toBe('demo_alice')
    expect((wrapper.find('#auth-password').element as HTMLInputElement).value).toBe('DemoPass123!')
  })

  it('2. ProfileView embeds DisplaySettings in 显示设置 tab and uses ConfirmDialog for family grant revocation', async () => {
    const router = makeRouter('/me')
    await router.isReady()
    const auth = useAuthStore()
    auth.user = {
      id: 'u-owner',
      account: 'owner_acc',
      nickname: '林阿姨',
      bio: '每天散步半小时',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: false,
      created_at: '2026-11-26T00:00:00Z',
    }

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.includes('/me/family/grants')) {
        return Promise.resolve(
          jsonResponse({
            granted_by_me: [
              {
                id: 'grant-1',
                granter_id: 'u-owner',
                viewer_id: 'u-child',
                viewer_nickname: '女儿小敏',
                status: 'active',
                share_plan_summary: true,
                share_weekly_sleep: false,
                share_weekly_activity: false,
              },
            ],
            granted_to_me: [],
          })
        )
      }
      if (method === 'DELETE' && url.includes('/me/family/grants/grant-1')) {
        return Promise.resolve(jsonResponse({ ok: true }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })

    const wrapper = mount(ProfileView, { global: { plugins: [router] } })
    await flushPromises()

    // Grouped tabs include 个人资料, 显示设置, 收藏与历史, 家庭关怀, 数据与隐私
    const tabLabels = wrapper.findAll('[role="tab"]').map((t) => t.text())
    expect(tabLabels).toEqual(['个人资料', '显示设置', '收藏与历史', '家庭关怀', '数据与隐私'])

    // Switch to 显示设置 -> renders DisplaySettings controls
    const displayTab = wrapper.findAll('[role="tab"]').find((t) => t.text() === '显示设置')!
    await displayTab.trigger('click')
    expect(wrapper.text()).toContain('大字阅读模式')
    expect(wrapper.text()).toContain('高对比度模式')

    // Switch to 家庭关怀 -> clicking 撤销授权 opens ConfirmDialog before sending DELETE
    const familyTab = wrapper.findAll('[role="tab"]').find((t) => t.text() === '家庭关怀')!
    await familyTab.trigger('click')
    await flushPromises()

    const revokeBtn = wrapper.findAll('button').find((b) => b.text() === '撤销授权')
    expect(revokeBtn).toBeDefined()
    await revokeBtn!.trigger('click')
    await flushPromises()

    // DELETE must not have fired yet before confirming in dialog
    const deleteCallsBefore = fetchSpy.mock.calls.filter(
      ([u, opts]) => String(u).includes('/me/family/grants/grant-1') && opts?.method === 'DELETE'
    )
    expect(deleteCallsBefore).toHaveLength(0)
    expect(wrapper.text()).toContain('确认撤销家庭关怀授权')

    const confirmRevokeBtn = wrapper.findAll('button').find((b) => b.text() === '确认撤销')
    expect(confirmRevokeBtn).toBeDefined()
    await confirmRevokeBtn!.trigger('click')
    await flushPromises()

    const deleteCallsAfter = fetchSpy.mock.calls.filter(
      ([u, opts]) => String(u).includes('/me/family/grants/grant-1') && opts?.method === 'DELETE'
    )
    expect(deleteCallsAfter).toHaveLength(1)
    expect(wrapper.text()).toContain('已撤销共享授权')
  })

  it('3. NotificationsView renders explicit 未读 and 已读 text badges (not color/dot alone) and handles unavailable target', async () => {
    const router = makeRouter('/notifications')
    await router.isReady()

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.includes('/me/notifications')) {
        return Promise.resolve(
          jsonResponse({
            unread_count: 1,
            items: [
              {
                id: 'n-unread',
                type: 'comment',
                target_type: 'post',
                target_id: 'p-hidden',
                summary: '陈伯伯评论了您的早睡分享',
                read_at: null,
                created_at: '2026-11-26T08:00:00Z',
                target_available: true,
              },
              {
                id: 'n-read',
                type: 'like',
                target_type: 'post',
                target_id: 'p-ok',
                summary: '林阿姨赞了您的散步打卡',
                read_at: '2026-11-26T09:00:00Z',
                created_at: '2026-11-25T18:00:00Z',
                target_available: true,
              },
            ],
          })
        )
      }
      if (method === 'POST' && url.includes('/me/notifications/n-unread/read')) {
        return Promise.resolve(jsonResponse({ target_available: false }))
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(NotificationsView, { global: { plugins: [router] } })
    await flushPromises()

    // Explicit text badges for both unread and read states
    const badgeTexts = wrapper.findAll('.badge').map((b) => b.text().trim())
    expect(badgeTexts).toContain('未读')
    expect(badgeTexts).toContain('已读')

    // Clicking notification whose target became unavailable stays on /notifications and shows 原内容已不可用
    const firstCard = wrapper.findAll('button.hl-notif-card, button.notif-card')[0]
    expect(firstCard).toBeDefined()
    await firstCard.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/notifications')
    expect(wrapper.text()).toContain('原内容已不可用')
  })

  it('4. ChallengesView renders accessible progressbar, zero leaderboard copy, and two-step ConfirmDialog before leaving', async () => {
    const router = makeRouter('/challenges')
    await router.isReady()

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.endsWith('/challenges')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'ch-sleep',
                slug: 'sleep-7d',
                title: '7 日规律睡眠记录',
                description: '连续 7 天记录入睡与起床感受，温和养成好作息。',
                rule_type: 'journal_sleep',
                target_days: 7,
                start_date: '2026-11-01',
                end_date: '2026-12-31',
                badge_title: '安眠同行者',
                joined: true,
                progress_days: 4,
                achieved: false,
              },
            ],
          })
        )
      }
      if (method === 'GET' && url.endsWith('/me/challenges')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                challenge_id: 'ch-sleep',
                progress_days: 4,
                target_days: 7,
                achieved: false,
              },
            ],
            badges: [],
          })
        )
      }
      if (method === 'DELETE' && url.includes('/challenges/ch-sleep/membership')) {
        return Promise.resolve(jsonResponse({ ok: true }))
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(ChallengesView, { global: { plugins: [router] } })
    await flushPromises()

    // Accessible progressbar with aria-valuenow / aria-valuemax and clear numeric label
    const bar = wrapper.find('[role="progressbar"]')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes('aria-valuenow')).toBe('4')
    expect(bar.attributes('aria-valuemin')).toBe('0')
    expect(bar.attributes('aria-valuemax')).toBe('7')
    expect(wrapper.text()).toContain('已完成 4 / 7 天')

    // Zero leaderboard / ranking copy
    expect(wrapper.text()).toContain('不排名、不攀比')
    expect(wrapper.text()).not.toMatch(/排行榜|击败了|第\s*\d+\s*名/)

    // Clicking 退出挑战 opens ConfirmDialog instead of immediately deleting membership
    const leaveBtn = wrapper.findAll('button').find((b) => b.text().includes('退出挑战'))
    expect(leaveBtn).toBeDefined()
    await leaveBtn!.trigger('click')
    await flushPromises()

    const deleteBefore = fetchSpy.mock.calls.filter(
      ([u, opts]) => String(u).includes('/challenges/ch-sleep/membership') && opts?.method === 'DELETE'
    )
    expect(deleteBefore).toHaveLength(0)

    const confirmLeaveBtn = wrapper.findAll('button').find((b) => b.text() === '确认退出')
    expect(confirmLeaveBtn).toBeDefined()
    await confirmLeaveBtn!.trigger('click')
    await flushPromises()

    const deleteAfter = fetchSpy.mock.calls.filter(
      ([u, opts]) => String(u).includes('/challenges/ch-sleep/membership') && opts?.method === 'DELETE'
    )
    expect(deleteAfter).toHaveLength(1)
  })

  it('5. AssistantView populates #assistant-query on safe example prompt click and keeps both consent checkboxes false by default', async () => {
    const router = makeRouter('/assistant')
    await router.isReady()
    const auth = useAuthStore()
    auth.publicConfig.assistant_enabled = true

    const wrapper = mount(AssistantView, { global: { plugins: [router] } })
    await flushPromises()

    // Capability & medical boundary notice present
    expect(wrapper.text()).toContain('不作为个体医疗诊断')

    // Consent checkboxes strictly default to false
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    expect(checkboxes).toHaveLength(2)
    expect((checkboxes[0].element as HTMLInputElement).checked).toBe(false)
    expect((checkboxes[1].element as HTMLInputElement).checked).toBe(false)

    // Clicking a safe example prompt chip populates #assistant-query without toggling consent
    const promptBtns = wrapper.findAll('button[data-testid="assistant-example-prompt"]')
    expect(promptBtns.length).toBeGreaterThanOrEqual(3)

    const firstPromptText = promptBtns[0].text().trim()
    await promptBtns[0].trigger('click')

    expect((wrapper.find('#assistant-query').element as HTMLTextAreaElement).value).toBe(firstPromptText)
    expect((checkboxes[0].element as HTMLInputElement).checked).toBe(false)
    expect((checkboxes[1].element as HTMLInputElement).checked).toBe(false)

    // Failed chat request preserves user's typed question for retry
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({ error: { code: 'UPSTREAM_TIMEOUT', message: '检索服务繁忙' } }, 502)
    )
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect((wrapper.find('#assistant-query').element as HTMLTextAreaElement).value).toBe(firstPromptText)
    expect(wrapper.find('[role="alert"]').text()).toContain('检索服务繁忙')
  })

  it('6. PublicUserView shows strict privacy boundary notice and OpsView preserves moderation resolution actions', async () => {
    const pubRouter = makeRouter('/users/u-bob')
    await pubRouter.isReady()

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({
        id: 'u-bob',
        nickname: '陈伯伯',
        bio: '喜欢傍晚去公园散步',
        is_demo: true,
        created_at: '2026-11-20T08:00:00Z',
        recent_posts: [
          {
            id: 'p-walk-1',
            title: '公园散步二十分钟心情舒畅',
            category: '运动与习惯',
            created_at: '2026-11-25T10:00:00Z',
          },
        ],
      })
    )

    const pubWrapper = mount(PublicUserView, { global: { plugins: [pubRouter] } })
    await flushPromises()
    expect(pubWrapper.text()).toContain('陈伯伯')
    expect(pubWrapper.text()).toContain('日常健康日记、习惯打卡与微挑战进度均严格保密')
    expect(pubWrapper.text()).toContain('公园散步二十分钟心情舒畅')

    // OpsView moderation hide workflow
    const opsRouter = makeRouter('/ops')
    await opsRouter.isReady()
    const auth = useAuthStore()
    auth.user = {
      id: 'u-mod',
      account: 'demo_mod',
      nickname: '社区治理员',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member', 'moderator', 'editor'],
      is_demo: true,
      created_at: '2026-11-20T00:00:00Z',
    }

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.includes('/moderation/reports')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'rep-1',
                target_type: 'post',
                target_id: 'p-bad',
                reason: 'misleading_medical',
                detail: '包含未经核实的偏方',
                status: 'pending',
                target_title: '某偏方帖',
                created_at: '2026-11-26T08:00:00Z',
              },
            ],
          })
        )
      }
      if (method === 'GET' && url.includes('/moderation/actions')) {
        return Promise.resolve(jsonResponse({ items: [] }))
      }
      if (method === 'POST' && url.includes('/moderation/reports/rep-1/resolve')) {
        return Promise.resolve(jsonResponse({ ok: true }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })

    const opsWrapper = mount(OpsView, { global: { plugins: [opsRouter] } })
    await flushPromises()
    expect(opsWrapper.text()).toContain('某偏方帖')

    const hideBtn = opsWrapper.findAll('button').find((b) => b.text() === '隐藏内容')
    expect(hideBtn).toBeDefined()
    await hideBtn!.trigger('click')
    await flushPromises()
    expect(opsWrapper.text()).toContain('已处理并隐藏目标内容')
  })
})
