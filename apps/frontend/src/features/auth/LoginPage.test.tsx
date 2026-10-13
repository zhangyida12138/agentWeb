import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { installFetchMock } from '../../test/api-mock'

import { LoginPage } from './LoginPage'
import type { AuthUser } from './types'

const USER: AuthUser = {
  id: '018f0000-0000-7000-8000-000000000001',
  email: 'alice@example.com',
  username: 'alice',
  display_name: 'Alice',
  avatar_url: null,
  bio: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const STORAGE_KEY = 'agent-web.auth'

function renderWithProviders(ui: ReactElement) {
  // 每个用例独立的 QueryClient：复用同一个会让上一条缓存串进下一个用例
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={ui} />
          <Route path="/" element={<div>home-page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 表单提交统一走 submit 事件：不依赖 jsdom 对「点提交按钮触发提交」的实现细节。 */
function submitForm() {
  const form = screen.getByRole('button', { name: '登录' }).closest('form')
  expect(form).not.toBeNull()
  fireEvent.submit(form as HTMLFormElement)
}

describe('LoginPage', () => {
  it('登录成功后把 token 写入 localStorage 并跳转到首页', async () => {
    installFetchMock((url) => {
      if (url.endsWith('/auth/login')) {
        return {
          data: {
            token: { access_token: 'token-1', token_type: 'bearer', expires_in: 3600 },
            user: USER,
          },
        }
      }
      return { status: 404, code: 40400, message: '接口不存在' }
    })

    renderWithProviders(<LoginPage />)

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret123' } })
    submitForm()

    expect(await screen.findByText('home-page')).toBeInTheDocument()

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
    expect(stored.token).toBe('token-1')
    expect(stored.user.username).toBe('alice')
  })

  it('邮箱或密码错误时展示顶部提示，且不写入登录态', async () => {
    installFetchMock(() => ({
      status: 401,
      code: 40110,
      message: '邮箱或密码错误',
    }))

    renderWithProviders(<LoginPage />)

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong-password' } })
    submitForm()

    expect(await screen.findByText('邮箱或密码错误')).toBeInTheDocument()
    // 失败时不能留下任何登录痕迹，否则刷新页面会被守卫当成「已登录」
    await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toBeNull())
  })

  it('本地校验不通过时不发请求', async () => {
    const fetchMock = installFetchMock(() => ({ data: null }))

    renderWithProviders(<LoginPage />)

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'not-an-email' } })
    submitForm()

    expect(await screen.findByText('邮箱格式不正确')).toBeInTheDocument()
    expect(await screen.findByText('请输入密码')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
