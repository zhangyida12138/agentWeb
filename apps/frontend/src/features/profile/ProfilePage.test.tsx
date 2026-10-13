import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { bodyOf, installFetchMock } from '../../test/api-mock'
import type { AuthUser } from '../auth/types'

import { ProfilePage } from './ProfilePage'

const USER: AuthUser = {
  id: '018f0000-0000-7000-8000-000000000001',
  email: 'alice@example.com',
  username: 'alice',
  display_name: 'Alice',
  avatar_url: null,
  bio: '写点东西',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      {/* 页面上有指向 /change-password 的 <Link>，没有 Router 会直接抛
          「Cannot destructure property 'basename'」把整个页面渲染炸掉 */}
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProfilePage', () => {
  it('加载并展示账户信息', async () => {
    installFetchMock((url) =>
      url.endsWith('/auth/me')
        ? { data: USER }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderPage()

    expect(await screen.findByText('alice@example.com')).toBeInTheDocument()
    expect(screen.getByText('写点东西')).toBeInTheDocument()
  })

  it('PATCH 只提交改动过的字段（空串表示清空，转成 null）', async () => {
    const fetchMock = installFetchMock((url, init) => {
      if (!url.endsWith('/auth/me')) return { status: 404, code: 40400, message: '接口不存在' }
      if (init.method === 'PATCH') return { data: { ...USER, display_name: 'Alice 2' } }
      return { data: USER }
    })

    renderPage()

    const displayNameInput = await screen.findByLabelText('显示名')
    fireEvent.change(displayNameInput, { target: { value: 'Alice 2' } })
    fireEvent.change(screen.getByLabelText('个人简介'), { target: { value: '' } })

    const form = screen.getByRole('button', { name: '保存修改' }).closest('form')
    fireEvent.submit(form as HTMLFormElement)

    await waitFor(() => expect(screen.getByText('资料已保存')).toBeInTheDocument())

    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'PATCH',
    )
    expect(patchCall).toBeDefined()
    const body = bodyOf(patchCall?.[1] as RequestInit | undefined)

    // 关键断言：改过的两个字段在，没碰过的 avatar_url 不在
    // ——多带一个键就等于把「没修改」当成「改成空」提交，PATCH 语义会被破坏
    expect(body).toEqual({ display_name: 'Alice 2', bio: null })
    expect(body).not.toHaveProperty('avatar_url')
  })

  it('没有任何改动时保存按钮不可用', async () => {
    installFetchMock(() => ({ data: USER }))

    renderPage()

    const saveButton = await screen.findByRole('button', { name: '保存修改' })
    expect(saveButton).toBeDisabled()
  })
})
