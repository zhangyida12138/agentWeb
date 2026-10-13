import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { setAuth } from '../../stores/auth'
import { installFetchMock } from '../../test/api-mock'

import { ChangePasswordPage } from './ChangePasswordPage'
import type { AuthUser } from './types'

const STORAGE_KEY = 'agent-web.auth'

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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      {/* 页面里有「返回个人中心」链接，所以必须在 Router 里渲染 */}
      <MemoryRouter>
        <ChangePasswordPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function fillPasswords(oldPassword: string, newPassword: string, confirm = newPassword) {
  fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: oldPassword } })
  fireEvent.change(screen.getByLabelText('新密码'), { target: { value: newPassword } })
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: confirm } })
}

function submitForm() {
  const form = screen.getByRole('button', { name: '修改密码' }).closest('form')
  expect(form).not.toBeNull()
  fireEvent.submit(form as HTMLFormElement)
}

/** 改密是登录后才能做的事，所以每个用例都先造出一个已登录的现场。 */
function signIn() {
  setAuth({ access_token: 'token-1', token_type: 'bearer', expires_in: 3600 }, USER)
}

describe('ChangePasswordPage', () => {
  it('修改成功后清空输入框并给出提示（明文不留存在 DOM 里）', async () => {
    signIn()
    installFetchMock((url) =>
      url.endsWith('/auth/changepassword')
        ? { data: null, message: '密码修改成功' }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderPage()
    fillPasswords('old-secret', 'new-secret')
    submitForm()

    expect(await screen.findByText('密码已修改')).toBeInTheDocument()
    expect((screen.getByLabelText('当前密码') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('新密码') as HTMLInputElement).value).toBe('')
  })

  it('原密码不正确（401 + 40110）时只提示，不清除登录态', async () => {
    signIn()
    installFetchMock(() => ({ status: 401, code: 40110, message: '原密码不正确' }))

    renderPage()
    fillPasswords('wrong-old', 'new-secret')
    submitForm()

    expect(await screen.findByText('原密码不正确')).toBeInTheDocument()

    // 回归点：40110 也是 401，但它表示「旧密码不对」而不是「登录失效」。
    // lib/api.ts 特意把它排除在 clearAuth 之外——否则用户打错一次旧密码就会被登出。
    expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull()
  })

  it('新密码与当前密码相同或两次不一致时本地拦下，不发请求', async () => {
    signIn()
    const fetchMock = installFetchMock(() => ({ data: null }))

    renderPage()
    fillPasswords('same-secret', 'same-secret')
    submitForm()
    expect(await screen.findByText('新密码不能与当前密码相同')).toBeInTheDocument()

    fillPasswords('old-secret', 'new-secret', 'new-secret2')
    submitForm()
    expect(await screen.findByText('两次输入的新密码不一致')).toBeInTheDocument()

    expect(fetchMock).not.toHaveBeenCalled()
  })
})
