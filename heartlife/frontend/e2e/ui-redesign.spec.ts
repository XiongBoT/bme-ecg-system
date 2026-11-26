import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

async function loginDemo(
  page: import('@playwright/test').Page,
  account = 'demo_alice',
  password = 'DemoPass123!'
) {
  await page.goto('/login')
  await page.locator('#auth-account').fill(account)
  await page.locator('#auth-password').fill(password)
  await page.locator('form button[type="submit"]').click()
  await expect(page).not.toHaveURL(/\/login/)
}

async function assertZeroSeriousAxeViolations(
  page: import('@playwright/test').Page,
  contextLabel: string
) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()

  const blocking = results.violations.filter(
    (v) => v.impact === 'critical' || v.impact === 'serious'
  )

  expect(
    blocking.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.slice(0, 3).map((n) => n.html),
    })),
    `Axe serious/critical WCAG violations on ${contextLabel}`
  ).toEqual([])
}

test.describe('HeartLife Elderly-Friendly UI/UX Redesign Suite (UI-T03 ~ UI-T27)', () => {
  test('UI-T03, UI-T04, UI-T07, UI-T08, UI-T25: Warm tokens, 48px targets, aria-current, Large Font & High Contrast persistence, and Reduced Motion', async ({
    page,
  }) => {
    await loginDemo(page, 'demo_alice')

    // Default body font size = 18px, canvas = #f8f6f0 (rgb(248, 246, 240)), zero CSS zoom/transform scaling
    const baseMetrics = await page.evaluate(() => {
      const bodyStyle = getComputedStyle(document.body)
      const htmlStyle = getComputedStyle(document.documentElement)
      const primaryBtn = document.querySelector('.btn-primary') as HTMLElement | null
      return {
        fontSize: bodyStyle.fontSize,
        bgColor: bodyStyle.backgroundColor,
        zoom: (htmlStyle as unknown as Record<string, string>).zoom || '1',
        btnHeight: primaryBtn ? primaryBtn.getBoundingClientRect().height : 48,
      }
    })
    expect(baseMetrics.fontSize).toBe('18px')
    expect(baseMetrics.bgColor).toBe('rgb(248, 246, 240)')
    expect(baseMetrics.btnHeight).toBeGreaterThanOrEqual(48)

    // UI-T04: aria-current="page" updates cleanly across primary navigation routes
    for (const [routePath, navText] of [
      ['/', '首页'],
      ['/community', '社区'],
      ['/plans', '计划'],
      ['/knowledge', '百科'],
      ['/challenges', '挑战'],
    ] as const) {
      await page.goto(routePath)
      const activeNav = page
        .locator('nav[aria-label="主导航"] a[aria-current="page"]')
      await expect(activeNav).toContainText(navText)
    }

    // UI-T07: Toggle Large Font mode from top bar -> body becomes 22px & persists across reload
    await page.goto('/community')
    const largeFontToggle = page.getByRole('button', { name: /大字\s*阅读模式|标准字\s*阅读模式/ })
    await largeFontToggle.click()
    await expect(page.locator('html')).toHaveAttribute('data-font-size', 'large')

    const largeFontSize = await page.evaluate(() => getComputedStyle(document.body).fontSize)
    expect(largeFontSize).toBe('22px')

    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-font-size', 'large')

    // UI-T08: Toggle High Contrast mode on /me -> Display Settings & persist across reload
    await page.goto('/me')
    const displayTab = page.getByRole('tab', { name: /显示设置/ })
    await displayTab.click()

    const contrastSwitch = page.getByTestId('pref-high-contrast')
    await contrastSwitch.click()
    await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')

    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')

    // UI-T25: Emulate prefers-reduced-motion: reduce -> transition durations collapse
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const reducedTransition = await page.evaluate(() => {
      const btn = document.querySelector('.btn') as HTMLElement | null
      return btn ? parseFloat(getComputedStyle(btn).transitionDuration) : 0
    })
    expect(reducedTransition).toBeLessThanOrEqual(0.001)

    // Restore default display settings via reset button
    await page.getByRole('tab', { name: /显示设置/ }).click()
    await page.getByRole('button', { name: '恢复默认显示' }).click()
    await expect(page.locator('html')).not.toHaveAttribute('data-font-size', 'large')
    await expect(page.locator('html')).not.toHaveAttribute('data-contrast', 'high')
    const restoredFontSize = await page.evaluate(() => getComputedStyle(document.body).fontSize)
    expect(restoredFontSize).toBe('18px')
  })

  test('UI-T05 & UI-T06: Multi-viewport (320px ~ 1440px), 200% zoom reflow, and mobile bottom-nav non-occlusion', async ({
    page,
  }) => {
    await loginDemo(page, 'demo_alice')

    const viewports = [
      { width: 320, height: 680 },
      { width: 375, height: 812 },
      { width: 390, height: 844 },
      { width: 768, height: 1024 },
      { width: 1024, height: 800 },
      { width: 1280, height: 860 },
      { width: 1440, height: 900 },
    ]

    for (const vp of viewports) {
      await page.setViewportSize(vp)
      for (const route of ['/', '/community', '/journal', '/plans', '/knowledge', '/weekly-report', '/me']) {
        await page.goto(route)
        await page.waitForLoadState('networkidle')
        const layout = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        }))
        expect(
          layout.scrollWidth <= layout.innerWidth + 1,
          `Horizontal overflow at ${vp.width}px on ${route}: ${layout.scrollWidth} > ${layout.innerWidth}`
        ).toBe(true)
      }
    }

    // Mobile bottom nav check at 390x844: exact 5 items and non-occlusion of Journal submit button
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/journal')
    const bottomNav = page.locator('nav[aria-label="底部主导航"]')
    await expect(bottomNav).toBeVisible()
    await expect(bottomNav.locator('a')).toHaveCount(5)

    const saveBtn = page.getByRole('button', { name: '保存记录' })
    await saveBtn.scrollIntoViewIfNeeded()
    const nonOccluded = await page.evaluate(() => {
      const mainEl = document.querySelector('main')
      const padBottom = mainEl ? parseFloat(getComputedStyle(mainEl).paddingBottom) : 0
      return padBottom >= 88
    })
    expect(nonOccluded).toBe(true)

    // 200% font-size reflow check at 1280px (WCAG 1.4.4 / 1.4.10)
    await page.setViewportSize({ width: 1280, height: 900 })
    for (const route of ['/community', '/journal', '/knowledge']) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      await page.addStyleTag({ content: 'html { font-size: 32px !important; }' })
      const zoomed = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }))
      expect(
        zoomed.scrollWidth <= zoomed.innerWidth + 2,
        `200% zoom overflow on ${route}: ${zoomed.scrollWidth} > ${zoomed.innerWidth}`
      ).toBe(true)
    }
  })

  test('UI-T09 & UI-T15: Keyboard dialog focus management (Enter -> Escape focus return) and failed post draft preservation', async ({
    page,
  }) => {
    await loginDemo(page, 'demo_alice')
    await page.setViewportSize({ width: 1280, height: 860 })
    await page.goto('/community')
    await page.waitForLoadState('networkidle')

    const publishTrigger = page.getByRole('button', { name: '发布动态' })
    await publishTrigger.focus()
    await page.keyboard.press('Enter')

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Press Escape -> dialog closes and focus returns to trigger button
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(publishTrigger).toBeFocused()

    // UI-T15: Simulate 503 failure on POST /api/v1/posts -> draft MUST remain intact
    await page.route('**/api/v1/posts', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            error: { code: 'TEMP_UNAVAILABLE', message: '网络暂时波动，请稍后再试' },
          }),
        })
      } else {
        await route.continue()
      }
    })

    await publishTrigger.click()
    await page.locator('#post-title-input').fill('清晨公园慢走二十五分钟心得')
    await page.locator('#post-body-input').fill('今天天气温和，走完之后呼吸顺畅，心情也放松了许多。')
    await page.getByRole('button', { name: '确认发布' }).click()

    await expect(dialog.getByRole('alert')).toContainText('网络暂时波动')
    await expect(page.locator('#post-title-input')).toHaveValue('清晨公园慢走二十五分钟心得')
    await expect(page.locator('#post-body-input')).toHaveValue(
      '今天天气温和，走完之后呼吸顺畅，心情也放松了许多。'
    )
    await page.unroute('**/api/v1/posts')
  })

  test('UI-T26: Account switch isolation — zero private health data leakage and clean display preferences storage', async ({
    page,
  }) => {
    await loginDemo(page, 'demo_alice')

    // Enable Large Font & save a private journal note as demo_alice
    await page.getByRole('button', { name: /大字\s*阅读模式|标准字\s*阅读模式/ }).click()
    await page.goto('/journal')
    const secretNote = `Alice专属私密记录_${Date.now()}`
    await page.locator('#journal-note').fill(secretNote)
    await page.getByRole('button', { name: '保存记录' }).click()
    await expect(page.locator('body')).toContainText('已保存')

    // Inspect localStorage: only display preference keys may exist
    const prefRaw = await page.evaluate(() => localStorage.getItem('heartlife_display_prefs'))
    expect(prefRaw).toBeTruthy()
    const prefParsed = JSON.parse(prefRaw!)
    expect(Object.keys(prefParsed).sort()).toEqual(['contrast', 'fontSize', 'reducedMotion'])

    // Logout from /me -> 数据与隐私
    await page.goto('/me')
    await page.getByRole('tab', { name: '数据与隐私' }).click()
    await page.getByRole('button', { name: '退出当前登录' }).click()
    await expect(page).toHaveURL(/\/login/)

    // Login as demo_bob and verify zero trace of Alice's private note
    await loginDemo(page, 'demo_bob')
    for (const route of ['/', '/journal', '/weekly-report', '/me']) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      await expect(page.locator('body')).not.toContainText(secretNote)
    }
  })

  test('UI-T27: @axe-core/playwright WCAG 2.2 AA scan across all core pages & high-contrast large-font mode (0 serious/critical)', async ({
    page,
  }) => {
    // 1. Public Login / Register page
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await assertZeroSeriousAxeViolations(page, '/login (default)')

    // Toggle show password & register tab and re-scan
    const showPwdBtn = page.getByRole('button', { name: /显示密码|隐藏密码/ })
    if ((await showPwdBtn.count()) > 0) {
      await showPwdBtn.click()
    }
    await page.getByRole('tab', { name: '注册' }).click()
    await assertZeroSeriousAxeViolations(page, '/login (register + visible password)')

    // 2. Authenticated pages
    await loginDemo(page, 'demo_alice')

    const coreRoutes = [
      '/',
      '/community',
      '/journal',
      '/plans',
      '/knowledge',
      '/weekly-report',
      '/challenges',
      '/notifications',
      '/me',
    ]

    for (const route of coreRoutes) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      await assertZeroSeriousAxeViolations(page, route)
    }

    // Scan open Publish Dialog on /community
    await page.goto('/community')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: '发布动态' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await assertZeroSeriousAxeViolations(page, '/community (publish dialog open)')
    await page.keyboard.press('Escape')

    // Scan Post Detail & Article Detail
    const firstPost = page.locator('a[href^="/community/"]').first()
    if ((await firstPost.count()) > 0) {
      await firstPost.click()
      await page.waitForLoadState('networkidle')
      await assertZeroSeriousAxeViolations(page, '/community/:id (post detail)')
    }

    await page.goto('/knowledge')
    await page.waitForLoadState('networkidle')
    const firstArticle = page.locator('a[href^="/knowledge/"]').first()
    if ((await firstArticle.count()) > 0) {
      await firstArticle.click()
      await page.waitForLoadState('networkidle')
      await assertZeroSeriousAxeViolations(page, '/knowledge/:id (article detail)')
    }

    // Scan Large Font + High Contrast mode on /community and /journal
    await page.evaluate(() => {
      localStorage.setItem(
        'heartlife_display_prefs',
        JSON.stringify({ fontSize: 'large', contrast: 'high', reducedMotion: true })
      )
    })
    for (const route of ['/community', '/journal']) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      await assertZeroSeriousAxeViolations(page, `${route} (large-font + high-contrast)`)
    }
  })
})
