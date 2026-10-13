import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { bodyOf, installFetchMock } from '../../test/api-mock'
import type { AuthUser } from '../auth/types'

import { UserManagementPage } from './UserManagementPage'
import type { AccessSummary, Role, UserPage } from './types'

/**
 * 用户管理页测试。
 *
 * 重点不在「能不能渲染出表格」，而在三条容易被写错、又很难在真机上发现的规则：
 *   ① 没权限时**不发**列表请求（前端已知会 403，就不该白跑一趟）；
 *   ② 保存角色是**替换**语义（提交出去的就是最终集合，不多不少）；
 *   ③ 重置密码必须两次一致，且成功后要显式告知「已有会话不会立刻失效」。
 * 第 ③ 条是后端刻意保留的限制（无状态 JWT，没有吊销名单），
 * 一旦这里的文案被删掉，管理员会把「重置密码」误当成「踢下线」。
 */

const ADMIN: AuthUser = {
  id: '018f0000-0000-7000-8000-000000000001',
  email: 'admin@example.com',
  username: 'admin',
  display_name: 'Admin',
  avatar_url: null,
  bio: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const BOB: AuthUser = {
  id: '018f0000-0000-7000-8000-000000000002',
  email: 'bob@example.com',
  username: 'bob',
  display_name: 'Bob',
  avatar_url: null,
  bio: null,
  is_active: true,
  created_at: '2026-02-01T00:00:00Z',
  updated_at: '2026-02-01T00:00:00Z',
}

const ROLES: Role[] = [
  {
    id: 'role-admin',
    code: 'admin',
    name: '管理员',
    description: '拥有全部权限',
    permission_codes: [],
  },
  { id: 'role-author', code: 'author', name: '作者', description: null, permission_codes: [] },
  { id: 'role-reader', code: 'reader', name: '读者', description: null, permission_codes: [] },
]

const USER_PAGE: UserPage = {
  items: [
    { user: ADMIN, role_codes: ['admin'] },
    { user: BOB, role_codes: ['reader'] },
  ],
  total: 2,
  offset: 0,
  limit: 20,
}

/** 管理员：三个权限都有。 */
const ACCESS_ADMIN: AccessSummary = {
  role_codes: ['admin'],
  permission_codes: ['user:list', 'user:assign_roles', 'user:reset_password', 'role:list'],
}

/** 只读管理员：只能看列表，改不了任何东西。 */
const ACCESS_READONLY: AccessSummary = { role_codes: ['author'], permission_codes: ['user:list'] }

/** 普通用户：连列表都不该看。 */
const ACCESS_NONE: AccessSummary = { role_codes: ['reader'], permission_codes: ['role:list'] }

const NOT_FOUND = { status: 404, code: 40400, message: '接口不存在' }

/**
 * 按 URL 分发的打桩。
 *
 * 判断顺序即优先级：`/users/{id}/roles` 与 `/users?offset=…` 都包含 `/users`，
 * 先粗后细地匹配会把「保存角色」这类请求误判成列表请求，
 * 于是断言会拿到一份用户分页数据而报出莫名其妙的错。
 */
function makeHandler(access: AccessSummary) {
  return (url: string) => {
    if (url.endsWith('/auth/me/access')) return { data: access }
    if (url.includes('/password')) return { data: { ...BOB, updated_at: '2026-03-01T00:00:00Z' } }
    // GET /roles（角色目录）与 PUT /users/{id}/roles（替换角色）返回的是同一种列表
    if (url.endsWith('/roles')) return { data: ROLES }
    if (url.includes('/users')) return { data: USER_PAGE }
    return NOT_FOUND
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <UserManagementPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

type FetchMock = ReturnType<typeof installFetchMock>

function passwordCalls(fetchMock: FetchMock) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes('/password'))
}

describe('UserManagementPage', () => {
  it('列出用户、角色徽章与两个管理动作', async () => {
    installFetchMock(makeHandler(ACCESS_ADMIN))

    renderPage()

    expect(await screen.findByText('bob@example.com')).toBeInTheDocument()
    expect(screen.getByText('Admin')).toBeInTheDocument()

    // 角色名来自角色目录（而不是页面上硬编码的映射），因此徽章显示的是 name 字段
    expect(screen.getByText('管理员')).toBeInTheDocument()
    expect(screen.getByText('读者')).toBeInTheDocument()

    expect(screen.getAllByRole('button', { name: '编辑角色' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: '重置密码' })).toHaveLength(2)
  })

  it('缺少 user:list 时不展示表格，且不发起用户列表请求', async () => {
    const fetchMock = installFetchMock(makeHandler(ACCESS_NONE))

    renderPage()

    expect(await screen.findByText(/你没有「查看用户列表」/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    // 关键：不是「请求失败后隐藏」，而是压根没请求
    const userListCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/users'))
    expect(userListCalls).toHaveLength(0)
  })

  it('保存角色时提交的是勾选后的完整集合（替换语义）', async () => {
    const fetchMock = installFetchMock(makeHandler(ACCESS_ADMIN))

    renderPage()
    await screen.findByText('bob@example.com')

    // 第二行是 Bob，他原本是读者
    fireEvent.click(screen.getAllByRole('button', { name: '编辑角色' })[1])

    const readerBox = await screen.findByRole('checkbox', { name: /读者/ })
    expect(readerBox).toBeChecked()

    fireEvent.click(readerBox)
    fireEvent.click(screen.getByRole('checkbox', { name: /作者/ }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    const putCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'PUT',
    )
    expect(String(putCall?.[0])).toContain(`/users/${BOB.id}/roles`)

    // 关键断言：只有 author，没有 reader。
    // 如果实现成「把勾选的并进原有集合」，这里会多出一个 reader——
    // 那样取消勾选就永远无效，权限只会越点越多
    expect(bodyOf(putCall?.[1] as RequestInit | undefined)).toEqual({ role_codes: ['author'] })
  })

  it('两次密码不一致时给出字段错误且不发请求', async () => {
    const fetchMock = installFetchMock(makeHandler(ACCESS_ADMIN))

    renderPage()
    await screen.findByText('bob@example.com')

    fireEvent.click(screen.getAllByRole('button', { name: '重置密码' })[1])
    await screen.findByRole('dialog')

    fireEvent.change(await screen.findByLabelText('新密码'), {
      target: { value: 'New-secret-1' },
    })
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'New-secret-2' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认重置' }))

    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument()
    expect(passwordCalls(fetchMock)).toHaveLength(0)
  })

  it('密码过短时给出长度错误且不发请求', async () => {
    const fetchMock = installFetchMock(makeHandler(ACCESS_ADMIN))

    renderPage()
    await screen.findByText('bob@example.com')

    fireEvent.click(screen.getAllByRole('button', { name: '重置密码' })[1])
    await screen.findByRole('dialog')

    fireEvent.change(await screen.findByLabelText('新密码'), { target: { value: 'short' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: '确认重置' }))

    expect(await screen.findByText('新密码至少 8 位')).toBeInTheDocument()
    expect(passwordCalls(fetchMock)).toHaveLength(0)
  })

  it('重置成功后明确提示已有登录状态不会失效', async () => {
    const fetchMock = installFetchMock(makeHandler(ACCESS_ADMIN))

    renderPage()
    await screen.findByText('bob@example.com')

    fireEvent.click(screen.getAllByRole('button', { name: '重置密码' })[1])
    await screen.findByRole('dialog')

    fireEvent.change(await screen.findByLabelText('新密码'), {
      target: { value: 'New-secret-1' },
    })
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'New-secret-1' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认重置' }))

    expect(await screen.findByText('密码已重置')).toBeInTheDocument()

    // 这条文案是契约的一部分，与后端 test_reset_password_leaves_existing_tokens_valid 对应
    expect(screen.getByText(/重置密码不会让该用户已登录的设备立即下线/)).toBeInTheDocument()

    const calls = passwordCalls(fetchMock)
    expect(calls).toHaveLength(1)
    expect(String(calls[0][0])).toContain(`/users/${BOB.id}/password`)
    expect(bodyOf(calls[0][1] as RequestInit | undefined)).toEqual({
      new_password: 'New-secret-1',
    })
  })

  it('只有 user:list 权限时列表只读（不显示任何操作按钮）', async () => {
    installFetchMock(makeHandler(ACCESS_READONLY))

    renderPage()

    expect(await screen.findByText('bob@example.com')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑角色' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重置密码' })).not.toBeInTheDocument()
  })
})
