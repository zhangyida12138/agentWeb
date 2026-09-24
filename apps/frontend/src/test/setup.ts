import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// 未开启 globals，需手动在每个用例后卸载已挂载的组件
afterEach(() => {
  cleanup()
})
