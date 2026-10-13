import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { bodyOf, installFetchMock } from '../../test/api-mock'

import { LoginPage } from './LoginPage'
import { RegisterPage } from './RegisterPage'
import type { AuthUser } from './types'

const CREATED: AuthUser = {
  id: '018f0000-0000-7000-8000-000000000002',
  email: 'bob@example.com',
  username: 'bob',
  display_name: 'bob',
  avatar_url: null,
  bio: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

/**
 * 把 /login 也挂上真的 LoginPage：
 * 「注册成功后落到登录页并带上提示」是这个页面最核心的行为，
 * 只断言 navigate 被调用过没法验证提示和预填邮箱是否真的生效。
 */
function renderRegister() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/register']}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function fillRequired(password: string, confirm: string) {
  fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'bob@example.com' } })
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'bob' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: password } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: confirm } })
}

function submitForm() {
  const form = screen.getByRole('button', { name: '注册' }).closest('form')
  expect(form).not.toBeNull()
  fireEvent.submit(form as HTMLFormElement)
}

describe('RegisterPage', () => {
  it('注册成功后跳转登录页：提示可见、邮箱已预填，且未自行登录', async () => {
    const fetchMock = installFetchMock((url) =>
      url.endsWith('/auth/register')
        ? { status: 201, data: CREATED }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderRegister()
    fillRequired('secret123', 'secret123')
    submitForm()

    expect(await screen.findByText('注册成功，请使用刚才设置的密码登录')).toBeInTheDocument()
    expect((screen.getByLabelText('邮箱') as HTMLInputElement).value).toBe('bob@example.com')

    // 请求体形状：空显示名要转成 null（后端语义是「没填」，不是「填了个空串」）
    const call = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/auth/register'))
    expect(call?.[1]?.method).toBe('POST')
    expect(bodyOf(call?.[1])).toEqual({
      email: 'bob@example.com',
      username: 'bob',
      password: 'secret123',
      display_name: null,
    })

    // 注册不签发 token：这一步绝不能留下登录态，否则会绕过登录直接进首页
    expect(localStorage.getItem('agent-web.auth')).toBeNull()
  })

  it('邮箱已被注册（40910）时把错误挂到邮箱输入框上', async () => {
    // data.field 是后端「字段级错误」的约定（见 domain/identity/exceptions.py），
    // 少了它前端只能整表提示——这里必须照着真实响应造
    installFetchMock(() => ({
      status: 409,
      code: 40910,
      message: '该邮箱已被注册',
      data: { field: 'email' },
    }))

    renderRegister()
    fillRequired('secret123', 'secret123')
    submitForm()

    expect(await screen.findByText('该邮箱已被注册')).toBeInTheDocument()
    // 关键：错误是「字段级」的，不是笼统的顶部提示
    expect(screen.getByLabelText('邮箱')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('用户名')).not.toHaveAttribute('aria-invalid')
  })

  it('两次密码不一致时本地拦下，不发请求', async () => {
    const fetchMock = installFetchMock(() => ({ data: null }))

    renderRegister()
    fillRequired('secret123', 'secret124')
    submitForm()

    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('用户名含非法字符时本地拦下（与后端 pattern 对齐）', async () => {
    const fetchMock = installFetchMock(() => ({ data: null }))

    renderRegister()
    // 三个字（长度合规）但含中文：必须命中「合法字符」那条规则，
    // 否则测试会误判——两个字会先被长度规则拦下，测的就不是 pattern 了
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'bob@example.com' } })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: '张三丰' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret123' } })
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'secret123' } })
    submitForm()

    expect(await screen.findByText('用户名只能包含字母、数字、下划线或连字符')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
