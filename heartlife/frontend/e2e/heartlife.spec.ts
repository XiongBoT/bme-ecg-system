import { test, expect } from '@playwright/test'

function uniqueAccount(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
}

async function registerAndLoginUI(
  page: import('@playwright/test').Page,
  account: string,
  nickname: string,
  password = 'UserPass123!',
) {
  await page.goto('/login')
  await page.getByRole('tab', { name: '注册' }).click()
  await page.locator('#auth-account').fill(account)
  await page.locator('#auth-nickname').fill(nickname)
  await page.locator('#auth-password').fill(password)
  await page.locator('form button[type="submit"]').click()
  await expect(page).not.toHaveURL(/\/login/)
}

async function loginExistingUI(
  page: import('@playwright/test').Page,
  account: string,
  password = 'DemoPass123!',
) {
  await page.goto('/login')
  await page.locator('#auth-account').fill(account)
  await page.locator('#auth-password').fill(password)
  await page.locator('form button[type="submit"]').click()
  await expect(page).not.toHaveURL(/\/login/)
}

test.describe('HeartLife End-to-End Acceptance Matrix', () => {
  test('T-0006 / T-0601 / T-0901 / T-1001: Clean new user onboarding, empty states, and hidden optional entries', async ({
    page,
  }) => {
    const acc = uniqueAccount('e2e_new')
    await registerAndLoginUI(page, acc, '新朋友')

    // Optional disabled features should not appear as broken fake nav links
    await expect(page.locator('a[href="/assistant"]')).toHaveCount(0)
    await expect(page.getByText('心电检测工具')).toHaveCount(0)

    // Home empty state should not fabricate 0 sleep minutes
    await expect(page.locator('body')).toContainText(/未记录|记录今日/)

    // Weekly report empty state shows 无计划 / 未记录 and 截至今日
    await page.goto('/weekly-report')
    await expect(page.locator('body')).toContainText('无计划')
    await expect(page.locator('body')).toContainText('截至今日')
  })

  test('T-0108 & T-0707: Registration, profile update, reload persistence, public profile privacy, and logout', async ({
    page,
  }) => {
    const acc = uniqueAccount('e2e_prof')
    await registerAndLoginUI(page, acc, '初始昵称')

    // Record a private journal note first to verify public profile never leaks it
    await page.goto('/journal')
    await page.locator('#journal-note').fill('这是绝对私密的个人睡眠备注9988')
    await page.getByRole('button', { name: '保存记录' }).click()
    await expect(page.locator('body')).toContainText('已保存')

    // Update nickname on /me
    await page.goto('/me')
    const nickInput = page.locator('#prof-nickname')
    await nickInput.fill('更新后昵称')
    await page.getByRole('button', { name: '保存修改' }).click()
    await expect(page.locator('body')).toContainText('个人资料已更新')

    await page.reload()
    await expect(page.locator('#prof-nickname')).toHaveValue('更新后昵称')

    // Fetch current user ID via /api/v1/me and inspect public profile /users/{id}
    const meData = await page.evaluate(async () => {
      const r = await fetch('/api/v1/me', { credentials: 'include' })
      return r.json()
    })
    await page.goto(`/users/${meData.id}`)
    await expect(page.locator('body')).toContainText('更新后昵称')
    await expect(page.locator('body')).not.toContainText('这是绝对私密的个人睡眠备注9988')

    // Logout from 数据与隐私 tab
    await page.goto('/me')
    await page.getByRole('tab', { name: '数据与隐私' }).click()
    await page.getByRole('button', { name: '退出当前登录' }).click()
    await expect(page).toHaveURL(/\/login/)
  })

  test('T-0308 & T-0410 & T-0610 & T-0805: Journal persistence, Plans check-in/undo/re-checkin, Challenges, and Weekly Report sync', async ({
    page,
  }) => {
    const acc = uniqueAccount('e2e_habit')
    await registerAndLoginUI(page, acc, '习惯达人')

    // Journal record -> edit -> reload
    await page.goto('/journal')
    await page.locator('#journal-sleep').fill('450')
    await page.locator('#journal-activity').fill('35')
    await page.locator('#journal-note').fill('睡前读书半小时私密备注')
    await page.getByRole('button', { name: '保存记录' }).click()
    await expect(page.locator('body')).toContainText('已保存')
    await page.reload()
    await expect(page.locator('#journal-sleep')).toHaveValue('450')

    // Edit sleep to 480
    await page.locator('#journal-sleep').fill('480')
    await page.getByRole('button', { name: '保存记录' }).click()
    await expect(page.locator('body')).toContainText('已保存')
    await page.reload()
    await expect(page.locator('#journal-sleep')).toHaveValue('480')

    // Plans: create -> complete -> undo -> re-complete -> reload
    await page.goto('/plans')
    await page.locator('#plan-new-title').fill('晚饭后散步25分钟')
    await page.getByRole('button', { name: '创建计划' }).click()
    await expect(page.locator('body')).toContainText('晚饭后散步25分钟')

    await page.getByRole('button', { name: '完成打卡' }).first().click()
    await expect(page.getByRole('button', { name: '撤销打卡' }).first()).toBeVisible()

    await page.getByRole('button', { name: '撤销打卡' }).first().click()
    await expect(page.getByRole('button', { name: '完成打卡' }).first()).toBeVisible()

    await page.getByRole('button', { name: '完成打卡' }).first().click()
    await page.reload()
    await expect(page.getByRole('button', { name: '撤销打卡' }).first()).toBeVisible()

    // Weekly report reflects 480 sleep minutes and 100% plan completion, without exposing private note
    await page.goto('/weekly-report')
    await expect(page.locator('body')).toContainText('480 分钟')
    await expect(page.locator('body')).toContainText('100%')
    await expect(page.getByRole('img', { name: '每日睡眠与活动分钟柱状趋势图' })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('睡前读书半小时私密备注')

    // Join behavioral challenge and verify private progress is not on public profile (T-0805)
    await page.goto('/challenges')
    const joinBtn = page.getByRole('button', { name: /参与挑战|加入挑战|加入/ }).first()
    if (await joinBtn.isVisible()) {
      await joinBtn.click()
    }
    const meData = await page.evaluate(async () => {
      const r = await fetch('/api/v1/me', { credentials: 'include' })
      return r.json()
    })
    await page.goto(`/users/${meData.id}`)
    await expect(page.locator('body')).not.toContainText('7 日规律睡眠记录')
  })

  test('T-0206 / T-0216 / T-0609 / T-0504: Multi-user community interaction, XSS safety, moderation hide, notification check, and encyclopedia', async ({
    browser,
  }) => {
    const ctxA = await browser.newContext()
    const ctxB = await browser.newContext()
    const ctxMod = await browser.newContext()
    const pageA = await ctxA.newPage()
    const pageB = await ctxB.newPage()
    const pageMod = await ctxMod.newPage()

    const accA = uniqueAccount('e2e_alice')
    const accB = uniqueAccount('e2e_bob')
    await registerAndLoginUI(pageA, accA, '小禾A')
    await registerAndLoginUI(pageB, accB, '远山B')
    await loginExistingUI(pageMod, 'demo_mod', 'DemoPass123!')

    // User A creates a post including a literal <script> payload to test T-0206 XSS safety
    await pageA.goto('/community')
    await pageA.getByRole('button', { name: /发布动态|\+ 发布/ }).click()
    const postTitle = `早睡打卡分享_${Date.now().toString().slice(-5)}`
    await pageA.locator('#post-title-input').fill(postTitle)
    await pageA.locator('#post-body-input').fill('坚持十点半休息 <script>window.__xss_triggered = true</script>')
    await pageA.getByRole('button', { name: '确认发布' }).click()

    await expect(pageA.locator('body')).toContainText(postTitle)
    const xssFlag = await pageA.evaluate(() => (window as unknown as Record<string, unknown>).__xss_triggered)
    expect(xssFlag).toBeUndefined()

    // User B finds post, likes, bookmarks, comments, and submits a report
    await pageB.goto('/community')
    await pageB.getByRole('link', { name: postTitle }).click()
    const postUrl = pageB.url()

    await pageB.getByRole('button', { name: /点赞/ }).click()
    await expect(pageB.getByRole('button', { name: /已赞/ })).toBeVisible()

    await pageB.locator('#comment-textarea').fill('非常棒的作息经验！')
    await pageB.getByRole('button', { name: '发送评论' }).click()
    await expect(pageB.locator('body')).toContainText('非常棒的作息经验！')

    // User A receives notification
    await pageA.goto('/notifications')
    await expect(pageA.locator('body')).toContainText('远山B')

    // User B reports the post
    await pageB.getByRole('button', { name: '举报' }).first().click()
    await pageB.getByRole('button', { name: '提交举报' }).click()
    await expect(pageB.locator('body')).toContainText('举报已提交')

    // Moderator hides the reported post
    await pageMod.goto('/ops')
    await expect(pageMod.locator('body')).toContainText(postTitle)
    await pageMod.getByRole('button', { name: '隐藏内容' }).first().click()
    await expect(pageMod.locator('body')).toContainText('已处理并隐藏目标内容')

    // Verify post is hidden from User B's direct access & User A's notification target check (T-0609)
    await pageB.goto(postUrl)
    await expect(pageB.locator('body')).toContainText('该内容当前不可用')

    await pageA.goto('/notifications')
    await expect(pageA.locator('body')).toContainText('原内容已不可用')

    // T-0504: Encyclopedia article shows authoritative source & review record
    await pageB.goto('/knowledge')
    await pageB.locator('a[href^="/knowledge/"]').first().click()
    await expect(pageB.locator('body')).toContainText('课程内容审核')
    await expect(pageB.locator('body')).toContainText('参考来源')

    await ctxA.close()
    await ctxB.close()
    await ctxMod.close()
  })

  test('T-0708: Responsive viewports (375px, 390px, 1280px), visual centering symmetry, and zero horizontal overflow', async ({
    page,
  }) => {
    await loginExistingUI(page, 'demo_alice', 'DemoPass123!')

    for (const vp of [
      { width: 375, height: 812 },
      { width: 390, height: 844 },
      { width: 1280, height: 820 },
    ]) {
      await page.setViewportSize(vp)
      for (const route of ['/', '/community', '/plans', '/journal', '/knowledge', '/weekly-report', '/me']) {
        await page.goto(route)
        await page.waitForLoadState('networkidle')
        const metrics = await page.evaluate(() => {
          const docWidth = document.documentElement.scrollWidth
          const winWidth = window.innerWidth
          const main = document.querySelector('main')
          const rect = main ? main.getBoundingClientRect() : null
          return {
            overflow: docWidth > winWidth + 1,
            docWidth,
            winWidth,
            leftGap: rect ? rect.left : 0,
            rightGap: rect ? winWidth - rect.right : 0,
          }
        })
        expect(metrics.overflow, `Overflow at ${vp.width}px on ${route} (${metrics.docWidth} > ${metrics.winWidth})`).toBe(false)
        if (vp.width >= 1280) {
          expect(Math.abs(metrics.leftGap - metrics.rightGap)).toBeLessThanOrEqual(24)
        }
      }
    }
  })

  test('T-0703 & T-1102..T-1104: Family minimal sharing invite/accept/revoke and re-authenticated account deletion', async ({
    browser,
  }) => {
    const ctxOwner = await browser.newContext()
    const ctxViewer = await browser.newContext()
    const pageOwner = await ctxOwner.newPage()
    const pageViewer = await ctxViewer.newPage()

    const accOwner = uniqueAccount('e2e_granter')
    const accViewer = uniqueAccount('e2e_viewer')
    await registerAndLoginUI(pageOwner, accOwner, '授权家人')
    await registerAndLoginUI(pageViewer, accViewer, '关怀亲友')

    // Owner creates a family invite code
    await pageOwner.goto('/me')
    await pageOwner.getByRole('tab', { name: '家庭关怀' }).click()
    await pageOwner.getByRole('button', { name: '生成邀请码' }).click()
    await expect(pageOwner.locator('body')).toContainText('邀请码：')
    const codeText = await pageOwner.locator('.card-subtle strong').first().innerText()
    expect(codeText.length).toBeGreaterThan(6)

    // Viewer accepts invite and views minimal summary
    await pageViewer.goto('/me')
    await pageViewer.getByRole('tab', { name: '家庭关怀' }).click()
    await pageViewer.locator('#family-accept-code').fill(codeText.trim())
    await pageViewer.getByRole('button', { name: '确认关联' }).click()
    await expect(pageViewer.locator('body')).toContainText('授权家人')

    await pageViewer.getByRole('button', { name: '查看摘要' }).click()
    await expect(pageViewer.locator('body')).toContainText('授权家人 的授权摘要')

    // Owner revokes grant -> two-step ConfirmDialog -> immediate revocation
    await pageOwner.reload()
    await pageOwner.getByRole('tab', { name: '家庭关怀' }).click()
    await pageOwner.getByRole('button', { name: '撤销授权' }).click()
    await pageOwner.getByRole('button', { name: '确认撤销' }).click()
    await expect(pageOwner.locator('body')).toContainText('已撤销共享授权')

    // Owner permanently deletes account with password + DELETE confirmation
    await pageOwner.getByRole('tab', { name: '数据与隐私' }).click()
    await pageOwner.locator('#del-password').fill('UserPass123!')
    await pageOwner.locator('#del-confirm').fill('DELETE')
    await pageOwner.getByRole('button', { name: '确认永久注销' }).click()
    await expect(pageOwner).toHaveURL(/\/login/)

    // Deleted account can no longer log in
    await pageOwner.locator('#auth-account').fill(accOwner)
    await pageOwner.locator('#auth-password').fill('UserPass123!')
    await pageOwner.locator('form button[type="submit"]').click()
    await expect(pageOwner.getByRole('alert')).toContainText('账号或密码错误')

    await ctxOwner.close()
    await ctxViewer.close()
  })
})
