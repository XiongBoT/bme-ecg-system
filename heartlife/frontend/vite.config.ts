import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

const basePath = process.env.VITE_BASE_PATH || '/'
const releaseSha = process.env.VITE_RELEASE_SHA
if (releaseSha && !/^[0-9a-f]{40}$/.test(releaseSha)) {
  throw new Error('VITE_RELEASE_SHA must be a full lowercase source commit SHA')
}

export default defineConfig({
  // Root deployment remains supported; the existing ECG site uses /heartlife/.
  base: basePath,
  plugins: [vue(), tailwindcss(), {
    name: 'release-source',
    apply: 'build',
    generateBundle() {
      if (releaseSha) this.emitFile({
        type: 'asset',
        fileName: 'release-source.json',
        source: JSON.stringify({ schema: 1, source_sha: releaseSha, base_path: basePath }) + '\n',
      })
    },
  }],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.spec.ts'],
  },
})
