import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

import { clearAuth } from '../stores/auth'

/**
 * 测试全局 setup（由 vite.config.ts 的 test.setupFiles 引入）。
 *
 * 这里做三件所有测试都需要的事，避免每个用例各写一遍：
 *   ① jest-dom 断言（toBeInTheDocument 等）；
 *   ② 每个用例后卸载组件——vitest 未开 globals，RTL 的自动清理不会生效，
 *      不手动 cleanup 会让上一个用例的 DOM 串到下一个；
 *   ③ 清空 localStorage 并重置登录态单例。store 是模块级变量，跨用例不会自动复位，
 *      而上一个用例留下的 token 会让 RequireAuth 之类的断言结果完全反过来。
 */

beforeEach(() => {
  localStorage.clear()
  clearAuth()
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  clearAuth()
  // 测试里用 vi.stubGlobal('fetch', …) 替换了全局 fetch，
  // restoreAllMocks 不管这个，必须显式还原，否则会污染后续用例。
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
