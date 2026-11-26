import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(__dirname, '..')
const venvPython = path.resolve(rootDir, '.venv', 'Scripts', 'python.exe')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: {
    timeout: 8_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:8018',
    trace: 'retain-on-failure',
    channel: 'chrome',
  },
  projects: [
    {
      name: 'desktop-chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome', viewport: { width: 1280, height: 820 } },
    },
  ],
  webServer: {
    command: `"${venvPython}" "${path.resolve(rootDir, 'scripts', 'run_e2e_server.py')}"`,
    url: 'http://127.0.0.1:8018/api/v1/health',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
