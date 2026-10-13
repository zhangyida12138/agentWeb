import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { accessKeys } from '../features/access/api'
import { createQueryClient } from '../lib/query-client'
import { clearAuth, setAuth } from '../stores/auth'
import { installFetchMock } from '../test/api-mock'

import { AppLayout } from './AppLayout'

import type { AuthUser, TokenPayload } from '../features/auth/types'

/**
 * 导航栏的权限过滤。
 *
 * 定的规矩是：**看不见 + 说得清**，而不是「全都列出来再置灰」。
 * 置灰的入口对普通用户是纯粹的干扰——他既永远点不亮，也不知道为什么。
 * 看不见入口，加上直接敲地址时 `RequirePermission` 明说「缺哪个权限」，
 * 这组组合才是能自解释的。
 *
 * 注意这里断言的是「显示/不显示」这层 UX，不是安全边界：
 * 真正的鉴权在每个后端的 `require_permission` 上，
 * 前端少显示一个链接并不能阻止谁去调接口。
 */

function token(value: string): TokenPayload {
  return { access_token: value, token_type: 'bearer', expires_in: 3600 }
}

function makeUser(id: string, email: string, displayName: string): AuthUser {
  return {
    id,
    email,
    username: email.split('@')[0] ?? 'user',
    display_name: displayName,
    avatar_url: null,
    bio: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

const ADMIN_USER = makeUser('018f0000-0000-7000-8000-000000000001', 'admin@example.com', 'Admin')
const READER_USER = makeUser('018f0000-0000-7000-8000-000000000002', 'reader@example.com', 'Reader')

/** `GET /auth/me/access` 的出参形状。 */
function access(permissionCodes: string[]) {
  return { role_codes: [], permission_codes: permissionCodes }
}

/** 造一个「这个身份拥有这些权限」的后端。 */
function accessHandler(user: AuthUser, permissionCodes: string[]) {
  return (url: string) => {
    if (url.endsWith('/auth/me/access')) return { data: access(permissionCodes) }
    if (url.endsWith('/auth/me')) return { data: user }
    return { status: 404, code: 40400, message: '接口不存在' }
  }
}

/**
 * 渲染带导航的布局。
 *
 * QueryClient 由调用方传入：验证「换账号不继承缓存」时必须让两次挂载共用同一个实例，
 * 否则测的就不是缓存行为，而是「新实例天然没有旧数据」这个废话。
 */
function renderLayout(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<p>首页内容</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function newClient() {
  return createQueryClient()
}

const TAB = '用户管理'
function userManagementTab() {
  return screen.queryByRole('link', { name: TAB })
}

describe('AppLayout 导航的权限过滤', () => {
  it('有 user:list 时把用户管理入口放出来', async () => {
    setAuth(token('token-admin'), ADMIN_USER)
    installFetchMock(accessHandler(ADMIN_USER, ['user:list', 'role:list']))

    renderLayout(newClient())

    expect(await screen.findByRole('link', { name: TAB })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '首页' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '个人中心' })).toBeInTheDocument()
  })

  it('没有 user:list 时不显示入口，但基础入口照旧', async () => {
    setAuth(token('token-reader'), READER_USER)
    installFetchMock(accessHandler(READER_USER, ['comment:create']))

    const client = newClient()
    renderLayout(client)

    // 先确认这个身份的权限快照真的到了（否则「找不到入口」可能只是因为请求还没回来）
    await waitFor(() =>
      expect(client.getQueryData(accessKeys.myAccess)).toEqual(access(['comment:create'])),
    )

    expect(userManagementTab()).toBeNull()
    expect(screen.getByRole('link', { name: '首页' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '个人中心' })).toBeInTheDocument()
  })

  it('同一个标签页里换账号后，不会继承上一个账号的权限', async () => {
    const client = newClient()

    // ① 管理员登录：权限快照进缓存，且落在 5 分钟 staleTime 内
    setAuth(token('token-admin'), ADMIN_USER)
    installFetchMock(accessHandler(ADMIN_USER, ['user:list', 'role:list']))

    const first = renderLayout(client)
    expect(await screen.findByRole('link', { name: TAB })).toBeInTheDocument()
    first.unmount()

    // ② 退出 → 换成普通用户登录 → 重新挂载，仍然用同一个缓存实例
    clearAuth()
    setAuth(token('token-reader'), READER_USER)
    installFetchMock(accessHandler(READER_USER, ['comment:create']))

    renderLayout(client)

    // ③ 确认拿到的是普通用户自己的权限，而不是管理员那份残留
    await waitFor(() =>
      expect(client.getQueryData(accessKeys.myAccess)).toEqual(access(['comment:create'])),
    )
    expect(userManagementTab()).toBeNull()
  })
})
