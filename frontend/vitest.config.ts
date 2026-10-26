import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

/**
 * 前端单元测试配置（独立于 vite.config.ts）
 * - 只跑 tests/** 下的纯函数/组件测试
 * - 因为测的是纯函数，environment 用 node 即可；以后要测组件再换 happy-dom
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
})
