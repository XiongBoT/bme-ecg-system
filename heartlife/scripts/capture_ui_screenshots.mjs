import playwrightPkg from '../frontend/node_modules/@playwright/test/index.js'
const { chromium } = playwrightPkg
import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(__dirname, '..')
const phaseArg = process.argv.includes('--phase')
  ? process.argv[process.argv.indexOf('--phase') + 1]
  : 'before'

const outDir = path.resolve(rootDir, 'docs', 'screenshots', phaseArg)
const port = 8029
const baseUrl = `http://127.0.0.1:${port}`
const venvPy = path.resolve(rootDir, '.venv', 'Scripts', 'python.exe')

async function waitForReady(url, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(`${url}/api/v1/health`)
      if (r.ok) return
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error('Server failed to start within timeout')
}

async function main() {
  await fs.mkdir(outDir, { recursive: true })

  const serverProc = spawn(
    venvPy,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: path.resolve(rootDir, 'backend'),
      env: {
        ...process.env,
        APP_ENV: 'local',
        DEMO_MODE: '1',
        ASSISTANT_ENABLED: 'true',
      },
      stdio: 'ignore',
    }
  )

  try {
    await waitForReady(baseUrl)
    const browser = await chromium.launch({ channel: 'chrome' })

    // 1. Login screenshot (Desktop 1440x900 & Mobile 390x844)
    const anonCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const anonPage = await anonCtx.newPage()
    await anonPage.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
    await anonPage.screenshot({ path: path.join(outDir, 'desktop-login.png') })
    await anonPage.setViewportSize({ width: 390, height: 844 })
    await anonPage.screenshot({ path: path.join(outDir, 'mobile-login.png') })
    await anonCtx.close()

    // 2. Authenticated screenshots as synthetic demo_alice
    const authCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await authCtx.newPage()
    await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
    await page.locator('#auth-account').fill('demo_alice')
    await page.locator('#auth-password').fill('DemoPass123!')
    await page.locator('form button[type="submit"]').click()
    await page.waitForURL((u) => !u.pathname.includes('/login'))
    await page.waitForLoadState('networkidle')

    const pagesToCapture = [
      ['home', '/'],
      ['community', '/community'],
      ['plans', '/plans'],
      ['journal', '/journal'],
      ['knowledge', '/knowledge'],
      ['weekly-report', '/weekly-report'],
      ['me', '/me'],
    ]

    for (const [slug, routePath] of pagesToCapture) {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto(`${baseUrl}${routePath}`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(250)
      await page.screenshot({ path: path.join(outDir, `desktop-${slug}.png`) })

      await page.setViewportSize({ width: 390, height: 844 })
      await page.waitForTimeout(200)
      await page.screenshot({ path: path.join(outDir, `mobile-${slug}.png`) })
    }

    // Post detail screenshot
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`${baseUrl}/community`, { waitUntil: 'networkidle' })
    const firstPostLink = page.locator('a[href^="/community/"]').first()
    if ((await firstPostLink.count()) > 0) {
      await firstPostLink.click()
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(200)
      await page.screenshot({ path: path.join(outDir, 'desktop-post-detail.png') })
    }

    // If capturing 'after' phase, also capture Large Font & High Contrast modes on Community & Journal!
    if (phaseArg === 'after') {
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.addInitScript(() => {
        localStorage.setItem(
          'heartlife_display_prefs',
          JSON.stringify({ fontSize: 'large', contrast: 'default', reducedMotion: true })
        )
      })
      await page.goto(`${baseUrl}/community`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(250)
      await page.screenshot({ path: path.join(outDir, 'desktop-community-large-font.png') })
      await page.goto(`${baseUrl}/journal`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(250)
      await page.screenshot({ path: path.join(outDir, 'desktop-journal-large-font.png') })

      await page.evaluate(() => {
        localStorage.setItem(
          'heartlife_display_prefs',
          JSON.stringify({ fontSize: 'large', contrast: 'high', reducedMotion: true })
        )
      })
      await page.goto(`${baseUrl}/community`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(250)
      await page.screenshot({ path: path.join(outDir, 'desktop-community-high-contrast.png') })
      await page.goto(`${baseUrl}/journal`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(250)
      await page.screenshot({ path: path.join(outDir, 'desktop-journal-high-contrast.png') })
    }

    await authCtx.close()
    await browser.close()
    console.log(`Captured ${phaseArg} screenshots in ${outDir}`)
  } finally {
    serverProc.kill()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
