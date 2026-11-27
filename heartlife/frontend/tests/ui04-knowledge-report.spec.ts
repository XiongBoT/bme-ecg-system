import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import KnowledgeView from '../src/views/KnowledgeView.vue'
import ArticleDetailView from '../src/views/ArticleDetailView.vue'
import WeeklyReportView from '../src/views/WeeklyReportView.vue'
import ChartWithDataTable from '../src/components/common/ChartWithDataTable.vue'
import HealthMetricCard from '../src/components/common/HealthMetricCard.vue'
import { useAuthStore } from '../src/stores/auth'
import { setCsrfToken } from '../src/api/client'
import heartCoverSvg from '../src/assets/heartlife/illustrations/article-cover-heart.svg'
import sleepCoverSvg from '../src/assets/heartlife/illustrations/article-cover-sleep.svg'
import walkCoverSvg from '../src/assets/heartlife/illustrations/article-cover-walk.svg'

function makeRouter(initialPath = '/knowledge') {
  const Dummy = { template: '<div>stub</div>' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Dummy },
      { path: '/login', component: Dummy },
      { path: '/journal', component: Dummy },
      { path: '/knowledge', component: KnowledgeView },
      { path: '/knowledge/:id', component: ArticleDetailView },
      { path: '/weekly-report', component: WeeklyReportView },
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

const originalSpeechSynthesis = Object.getOwnPropertyDescriptor(window, 'speechSynthesis')
const originalUtterance = Object.getOwnPropertyDescriptor(window, 'SpeechSynthesisUtterance')

function restoreSpeechGlobals() {
  if (originalSpeechSynthesis) {
    Object.defineProperty(window, 'speechSynthesis', originalSpeechSynthesis)
  } else {
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, 'speechSynthesis')
  }
  if (originalUtterance) {
    Object.defineProperty(window, 'SpeechSynthesisUtterance', originalUtterance)
  } else {
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, 'SpeechSynthesisUtterance')
  }
}

describe('UI-04 Encyclopedia & Weekly Report Redesign Suite', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setCsrfToken('ui04-csrf-token')
    vi.restoreAllMocks()
    restoreSpeechGlobals()
  })

  afterEach(() => {
    restoreSpeechGlobals()
  })

  it('UI-T23: KnowledgeView renders editorial 3-col cards with local SVG covers, falls back cleanly on @error, and guards stale filter responses', async () => {
    const router = makeRouter('/knowledge')
    await router.isReady()

    let resolveSlowSearch: ((res: Response) => void) | null = null

    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/articles/categories')) {
        return Promise.resolve(
          jsonResponse({ categories: ['睡眠与休息', '运动与习惯', '心脏基础知识'] })
        )
      }
      if (url.includes('category=%E7%9D%A1%E7%9C%A0%E4%B8%8E%E4%BC%91%E6%81%AF')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 'art-sleep-only',
                slug: 'sleep-routine-guide',
                title: '睡前放松与规律作息指南',
                summary: '保持卧室安静温和，建立固定入睡节律。',
                category: '睡眠与休息',
                author_byline: 'HeartLife 睡眠科普组',
              },
            ],
            next_cursor: null,
          })
        )
      }
      if (url.includes('q=slow')) {
        return new Promise<Response>((resolve) => {
          resolveSlowSearch = resolve
        })
      }
      return Promise.resolve(
        jsonResponse({
          items: [
            {
              id: 'art-1',
              slug: 'sleep-well',
              title: '中老年安心睡眠小贴士',
              summary: '规律作息有助身心恢复。',
              category: '睡眠与休息',
              author_byline: 'HeartLife 科普组',
            },
            {
              id: 'art-2',
              title: '饭后温和散步习惯',
              summary: '循序渐进开展日常步行活动。',
              category: '运动与习惯',
              author_byline: 'HeartLife 运动组',
            },
            {
              id: 'art-3',
              title: '日常心率记录常识',
              summary: '科学认识静息心率波动。',
              category: '心脏基础知识',
              author_byline: 'HeartLife 科普组',
              cover_url: 'https://invalid.example.test/broken-cover.webp',
            },
          ],
          next_cursor: null,
        })
      )
    })

    const wrapper = mount(KnowledgeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('健康百科')
    expect(wrapper.text()).toContain('经课程内容审核的权威健康科普')
    expect(wrapper.find('.grid-3').exists()).toBe(true)

    const cards = wrapper.findAll('article.hl-article-card')
    expect(cards).toHaveLength(3)
    expect(cards[0].find('a[href="/knowledge/art-1"]').exists()).toBe(true)
    expect(cards[0].text()).toContain('阅读全文')

    const covers = wrapper.findAll('img.hl-article-cover')
    expect(covers).toHaveLength(3)
    expect(covers[0].attributes('src')).toBe(sleepCoverSvg)
    expect(covers[1].attributes('src')).toBe(walkCoverSvg)
    expect(covers[2].attributes('src')).toBe('https://invalid.example.test/broken-cover.webp')
    expect(covers[2].attributes('alt')).toBe('')
    expect(covers[2].attributes('aria-hidden')).toBe('true')

    // Trigger broken image @error -> must fall back cleanly to local heart SVG cover (UI-T23)
    await covers[2].trigger('error')
    expect(covers[2].attributes('src')).toBe(heartCoverSvg)

    // Stale response guard: start a slow search, then switch category before slow search resolves
    await wrapper.find('#knowledge-search').setValue('slow')
    await wrapper.find('form[role="search"]').trigger('submit.prevent')

    const sleepPill = wrapper.findAll('button.pill').find((b) => b.text() === '睡眠与休息')
    expect(sleepPill).toBeDefined()
    await sleepPill!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('睡前放松与规律作息指南')

    // Resolve the stale slow search late -> must NOT overwrite newer category results
    expect(resolveSlowSearch).not.toBeNull()
    resolveSlowSearch!(
      jsonResponse({
        items: [
          {
            id: 'stale-art',
            title: '过期旧搜索结果不应展示',
            summary: 'stale',
            category: '日常健康',
          },
        ],
      })
    )
    await flushPromises()

    expect(wrapper.text()).toContain('睡前放松与规律作息指南')
    expect(wrapper.text()).not.toContain('过期旧搜索结果不应展示')
  })

  it('UI-T21 + PRD §6: ArticleDetailView preserves review/source/scope transparency, rejects non-https source links, and hides TTS when unsupported', async () => {
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, 'speechSynthesis')
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, 'SpeechSynthesisUtterance')

    const router = makeRouter('/knowledge/art-detail-1')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 'u-reader',
      account: 'reader',
      nickname: '王阿姨',
      bio: '',
      timezone: 'Asia/Shanghai',
      roles: ['member'],
      is_demo: false,
      created_at: '2026-11-26T00:00:00Z',
    }

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (method === 'GET' && url.endsWith('/articles/art-detail-1')) {
        return Promise.resolve(
          jsonResponse({
            id: 'art-detail-1',
            title: '居家睡眠节律养护指南',
            summary: '温和建立规律作息的实用建议',
            category: '睡眠与休息',
            author_byline: '生医工课程科普编写组',
            updated_at: '2026-11-25T10:30:00Z',
            revision: 3,
            viewer_bookmarked: false,
            body: '第一段：保持卧室光线柔和与安静。\n\n第二段：睡前减少强光屏幕刺激。',
            scope_note: '本文仅供日常健康生活参考，不作为临床诊断或处方依据；如有持续不适请及时就医。',
            review_record: {
              reviewer: '陈教授（课程指导教师）',
              review_type: '课程内容审核',
              reviewed_at: '2026-11-24',
              note: '已核对睡眠卫生建议与表述边界',
            },
            sources: [
              {
                title: '世界卫生组织健康生活建议',
                url: 'https://www.who.int/health-topics',
                accessed_at: '2026-11-20',
              },
              {
                title: '非加密来源仅展示标题文本',
                url: 'http://insecure.example.org/sleep',
                accessed_at: '2026-11-19',
              },
            ],
          })
        )
      }
      if (method === 'PUT' && url.includes('/bookmarks/article/art-detail-1')) {
        return Promise.resolve(jsonResponse({ bookmarked: true }))
      }
      return Promise.resolve(jsonResponse({}))
    })

    const wrapper = mount(ArticleDetailView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.find('.reading-container').exists()).toBe(true)
    expect(wrapper.text()).toContain('返回健康百科')
    expect(wrapper.text()).toContain('课程内容审核')
    expect(wrapper.text()).toContain('陈教授（课程指导教师）')
    expect(wrapper.text()).toContain('已核对睡眠卫生建议与表述边界')
    expect(wrapper.text()).toContain('参考来源')
    expect(wrapper.text()).toContain('本文仅供日常健康生活参考，不作为临床诊断或处方依据')

    // HTTPS source renders as safe external link; HTTP source renders only as plain text
    const extLinks = wrapper.findAll('a[target="_blank"]')
    expect(extLinks).toHaveLength(1)
    expect(extLinks[0].attributes('href')).toBe('https://www.who.int/health-topics')
    expect(extLinks[0].attributes('rel')).toBe('noopener noreferrer')
    expect(wrapper.text()).toContain('非加密来源仅展示标题文本')
    expect(wrapper.find('a[href="http://insecure.example.org/sleep"]').exists()).toBe(false)

    // TTS button cleanly hidden when speechSynthesis is absent
    expect(wrapper.text()).not.toContain('朗读全文')

    // Bookmark toggle with aria-pressed
    const bookmarkBtn = wrapper.findAll('button').find((b) => b.text().includes('收藏文章'))
    expect(bookmarkBtn).toBeDefined()
    expect(bookmarkBtn!.attributes('aria-pressed')).toBe('false')
    await bookmarkBtn!.trigger('click')
    await flushPromises()
    expect(bookmarkBtn!.attributes('aria-pressed')).toBe('true')
    expect(bookmarkBtn!.text()).toContain('已收藏')
  })

  it('PRD §6: ArticleDetailView toggles local speechSynthesis on demand without auto-play and cancels on unmount', async () => {
    const instances: FakeUtterance[] = []
    class FakeUtterance {
      text: string
      lang = ''
      rate = 1
      onend: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor(text: string) {
        this.text = text
        instances.push(this)
      }
    }

    const cancelMock = vi.fn()
    const speakMock = vi.fn()

    Object.defineProperty(window, 'SpeechSynthesisUtterance', {
      configurable: true,
      writable: true,
      value: FakeUtterance,
    })
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      writable: true,
      value: {
        cancel: cancelMock,
        speak: speakMock,
      },
    })

    const router = makeRouter('/knowledge/art-tts')
    await router.isReady()

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      jsonResponse({
        id: 'art-tts',
        title: '温和散步指南',
        summary: '选择平坦步道循序渐进',
        category: '运动与习惯',
        author_byline: 'HeartLife 科普组',
        revision: 1,
        body: '散步前先做三分钟热身活动。',
        scope_note: '仅供健康生活参考，不作为医疗诊断依据。',
        review_record: {
          reviewer: '李老师',
          review_type: '课程内容审核',
          reviewed_at: '2026-11-25',
        },
        sources: [],
      })
    )

    const wrapper = mount(ArticleDetailView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    // Never auto-plays on mount
    expect(speakMock).not.toHaveBeenCalled()

    const ttsBtn = wrapper.findAll('button').find((b) => b.text().includes('朗读全文'))
    expect(ttsBtn).toBeDefined()
    expect(ttsBtn!.attributes('aria-pressed')).toBe('false')

    // Start local TTS
    await ttsBtn!.trigger('click')
    expect(cancelMock).toHaveBeenCalledTimes(1)
    expect(speakMock).toHaveBeenCalledTimes(1)
    expect(instances).toHaveLength(1)
    expect(instances[0].lang).toBe('zh-CN')
    expect(instances[0].rate).toBe(0.95)
    expect(instances[0].text).toContain('温和散步指南')
    expect(instances[0].text).toContain('选择平坦步道循序渐进')
    expect(instances[0].text).toContain('散步前先做三分钟热身活动。')
    expect(ttsBtn!.attributes('aria-pressed')).toBe('true')
    expect(ttsBtn!.text()).toContain('停止朗读')

    // Stop local TTS manually
    await ttsBtn!.trigger('click')
    expect(cancelMock).toHaveBeenCalledTimes(2)
    expect(ttsBtn!.attributes('aria-pressed')).toBe('false')
    expect(ttsBtn!.text()).toContain('朗读全文')

    // Start again, then unmount -> must always cancel speechSynthesis
    await ttsBtn!.trigger('click')
    expect(ttsBtn!.attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
    expect(cancelMock).toHaveBeenCalledTimes(4)
  })

  it('UI-T22: WeeklyReportView embeds ChartWithDataTable, distinguishes null (尚未记录) from 0 (0 分钟), and formats no-plan & partial-week states', async () => {
    const router = makeRouter('/weekly-report')
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
        journal_days: 2,
        observed_days: 4,
        sleep: { mean_minutes: null, valid_days: 0 },
        activity: { total_minutes: 0, valid_days: 1 },
        plans: { due: 0, completed: 0, completion_rate: null },
        daily_series: [
          {
            date: '2026-11-23',
            sleep_minutes: null,
            activity_minutes: 0,
            mood: 'good',
            plans_due: 0,
            plans_completed: 0,
          },
          {
            date: '2026-11-24',
            sleep_minutes: 480,
            activity_minutes: null,
            mood: null,
            plans_due: 2,
            plans_completed: 1,
          },
        ],
      })
    )

    const wrapper = mount(WeeklyReportView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.findComponent(ChartWithDataTable).exists()).toBe(true)
    expect(wrapper.findAllComponents(HealthMetricCard)).toHaveLength(4)
    expect(wrapper.find('a[href="/journal"]').exists()).toBe(true)

    expect(wrapper.text()).toContain('截至今日')
    expect(wrapper.text()).toContain('2 / 4 天')
    expect(wrapper.text()).toContain('尚未记录')
    expect(wrapper.text()).toContain('0 分钟')
    expect(wrapper.text()).toContain('无计划')
    expect(wrapper.text()).toContain('本周无应执行计划')

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('尚未记录')
    expect(rows[0].text()).toContain('0 分钟')
    expect(rows[0].text()).toContain('无计划')
    expect(rows[1].text()).toContain('480 分钟')
    expect(rows[1].text()).toContain('尚未记录')
    expect(rows[1].text()).toContain('1 / 2')
    wrapper.unmount()
  })
})
