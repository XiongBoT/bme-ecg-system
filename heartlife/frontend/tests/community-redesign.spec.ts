import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import CommunityView from '../src/views/CommunityView.vue'
import { useAuthStore } from '../src/stores/auth'
import { setCsrfToken } from '../src/api/client'

function makeRouter() {
  const Dummy = { template: '<div>详情</div>' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Dummy },
      { path: '/login', component: Dummy },
      { path: '/community', component: CommunityView },
      { path: '/community/:id', component: Dummy },
      { path: '/users/:id', component: Dummy },
    ],
  })
  router.push('/community')
  return router
}

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('UI-02 Flagship Community Redesign (UI-T10 ~ UI-T17)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setCsrfToken('csrf-community-test')
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('UI-T10 & UI-T17: Renders warm 2-column community with local avatar, community guidelines sidebar, and aria-pressed like/bookmark actions', async () => {
    const router = makeRouter()
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'u-alice',
      account: 'demo_alice',
      nickname: '林晓禾（演示）',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: true,
      created_at: '2026-11-26T00:00:00Z',
    }

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (url.includes('/me/follows/categories')) {
        return Promise.resolve(jsonResp({ categories: ['睡眠与休息'] }))
      }
      if (method === 'GET' && url.includes('/posts')) {
        return Promise.resolve(
          jsonResp({
            items: [
              {
                id: 'post-101',
                title: '清晨公园散步二十分钟的温暖感受',
                body: '每天早起喝杯温水再去散步，心情很舒畅。',
                category: '运动与习惯',
                tags: ['晨起散步'],
                author: { id: 'u-wang', nickname: '王秀兰（演示）', is_demo: true },
                like_count: 3,
                comment_count: 2,
                viewer_liked: false,
                viewer_bookmarked: false,
                is_demo: true,
                created_at: '2026-11-26T06:30:00Z',
              },
            ],
            next_cursor: null,
          })
        )
      }
      if (method === 'PUT' && url.endsWith('/posts/post-101/like')) {
        return Promise.resolve(jsonResp({ liked: true, like_count: 4 }))
      }
      if (method === 'PUT' && url.endsWith('/bookmarks/post/post-101')) {
        return Promise.resolve(jsonResp({ bookmarked: true }))
      }
      return Promise.resolve(jsonResp({}))
    })

    const wrapper = mount(CommunityView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('分享健康生活中的小事，互相鼓励、共同坚持。')
    expect(wrapper.text()).toContain('社区友善公约')
    expect(wrapper.text()).toContain('浏览话题')
    expect(wrapper.find('.hl-avatar').text()).toBe('王')

    const likeBtn = wrapper.find('[data-testid="post-like-post-101"]')
    expect(likeBtn.attributes('aria-pressed')).toBe('false')
    await likeBtn.trigger('click')
    await flushPromises()
    expect(likeBtn.attributes('aria-pressed')).toBe('true')
    expect(likeBtn.text()).toContain('4')

    const bmBtn = wrapper.find('[data-testid="post-bookmark-post-101"]')
    expect(bmBtn.attributes('aria-pressed')).toBe('false')
    await bmBtn.trigger('click')
    await flushPromises()
    expect(bmBtn.attributes('aria-pressed')).toBe('true')
    expect(fetchSpy).toHaveBeenCalled()
  })

  it('UI-T11 & UI-T12: Distinguishes true empty community (还没有内容) from empty search filter (没有找到相关内容 + 清除筛选)', async () => {
    const router = makeRouter()
    await router.isReady()

    let callIndex = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('q=')) {
        return Promise.resolve(jsonResp({ items: [], next_cursor: null }))
      }
      callIndex += 1
      if (callIndex === 1) {
        return Promise.resolve(jsonResp({ items: [], next_cursor: null }))
      }
      return Promise.resolve(
        jsonResp({
          items: [
            {
              id: 'p-restored',
              title: '恢复显示的真实分享',
              body: '内容正文',
              category: '日常健康',
              author: { id: 'u1', nickname: '陈远山' },
              created_at: '2026-11-26T08:00:00Z',
            },
          ],
          next_cursor: null,
        })
      )
    })

    const wrapper = mount(CommunityView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('还没有内容')
    expect(wrapper.text()).toContain('发布动态')

    await wrapper.find('#community-search').setValue('完全不存在的词')
    await wrapper.find('form[role="search"]').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('没有找到相关内容')
    const clearBtn = wrapper.find('[data-testid="community-clear-filters"]')
    expect(clearBtn.exists()).toBe(true)

    await clearBtn.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('恢复显示的真实分享')
  })

  it('UI-T13 & UI-T14: Shows skeleton/slow/error retry states and discards stale out-of-order filter responses', async () => {
    vi.useFakeTimers()
    const router = makeRouter()
    await router.isReady()

    let resolveSlowSport!: (r: Response) => void
    let failNext = false

    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = decodeURIComponent(String(input))
      if (failNext) {
        failNext = false
        return Promise.resolve(
          jsonResp({ error: { code: 'ERR', message: '服务连接波动' } }, 500)
        )
      }
      if (url.includes('category=运动与习惯')) {
        return new Promise<Response>((resolve) => {
          resolveSlowSport = resolve
        })
      }
      if (url.includes('category=睡眠与休息')) {
        return Promise.resolve(
          jsonResp({
            items: [
              {
                id: 'p-sleep',
                title: '最新睡眠分类分享',
                body: '安稳入睡经验',
                category: '睡眠与休息',
                author: { id: 'u2', nickname: '林晓禾' },
                created_at: '2026-11-26T09:00:00Z',
              },
            ],
            next_cursor: null,
          })
        )
      }
      return Promise.resolve(jsonResp({ items: [], next_cursor: null }))
    })

    const wrapper = mount(CommunityView, { global: { plugins: [router] } })
    await flushPromises()

    const sportTab = wrapper.findAll('button').find((b) => b.text().includes('运动与习惯'))!
    await sportTab.trigger('click')
    expect(wrapper.text()).toContain('正在加载')

    vi.advanceTimersByTime(10500)
    await flushPromises()
    expect(wrapper.text()).toContain('加载时间较长')

    const sleepTab = wrapper.findAll('button').find((b) => b.text().includes('睡眠与休息'))!
    await sleepTab.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('最新睡眠分类分享')

    resolveSlowSport(
      jsonResp({
        items: [
          {
            id: 'p-stale',
            title: '过期的运动旧响应不应覆盖当前页面',
            body: '旧数据',
            category: '运动与习惯',
            author: { id: 'u3', nickname: '旧作者' },
            created_at: '2026-11-26T07:00:00Z',
          },
        ],
        next_cursor: null,
      })
    )
    await flushPromises()
    expect(wrapper.text()).toContain('最新睡眠分类分享')
    expect(wrapper.text()).not.toContain('过期的运动旧响应不应覆盖当前页面')

    failNext = true
    const allTab = wrapper.findAll('button').find((b) => b.text() === '全部')!
    await allTab.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法加载，请重试')

    const retryBtn = wrapper.findAll('button').find((b) => b.text().includes('重试'))!
    await retryBtn.trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('暂时无法加载，请重试')
  })

  it('UI-T15 & UI-T16: Preserves draft when post creation fails and shows pending review notice when status is pending', async () => {
    const router = makeRouter()
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'u-alice',
      account: 'demo_alice',
      nickname: '林晓禾',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: false,
      created_at: '2026-11-26T00:00:00Z',
    }

    let postAttempt = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'POST' && url.endsWith('/posts')) {
        postAttempt += 1
        if (postAttempt === 1) {
          return Promise.resolve(
            jsonResp({ error: { code: 'BUSY', message: '发布暂时失败，请重试' } }, 503)
          )
        }
        return Promise.resolve(
          jsonResp({ id: 'p-pending-1', status: 'pending' }, 201)
        )
      }
      return Promise.resolve(jsonResp({ items: [], next_cursor: null }))
    })

    const wrapper = mount(CommunityView, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('[data-testid="community-open-publish"]').trigger('click')
    await flushPromises()

    const titleInput = wrapper.find('#post-title-input')
    const bodyInput = wrapper.find('#post-body-input')
    await titleInput.setValue('我认真撰写的散步心得')
    await bodyInput.setValue('每天傍晚慢走二十五分钟，心情很放松。')

    await wrapper.find('[data-testid="create-post-form"]').trigger('submit.prevent')
    await flushPromises()
    expect((titleInput.element as HTMLInputElement).value).toBe('我认真撰写的散步心得')
    expect((bodyInput.element as HTMLTextAreaElement).value).toBe('每天傍晚慢走二十五分钟，心情很放松。')
    expect(wrapper.text()).toContain('发布暂时失败')

    await wrapper.find('[data-testid="create-post-form"]').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.text()).toContain('待审核')
  })
})
