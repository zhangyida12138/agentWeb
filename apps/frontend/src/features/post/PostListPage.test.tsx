import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { createQueryClient } from '../../lib/query-client'
import { setAuth } from '../../stores/auth'
import { installFetchMock } from '../../test/api-mock'
import type { AuthUser, TokenPayload } from '../auth/types'

import { PostListPage } from './PostListPage'

import type { PostSummary } from './types'

/**
 * 公开文章列表（「未登录也能看」这条决定的主要载体）。
 *
 * 这里最要紧的一条断言不是「文章显示出来了」，而是**游客没有去打需要登录的接口**。
 * `/auth/me` 与 `/auth/me/access` 都要求认证，未登录时必然 401，
 * 而前端 api 层在 401 时会清掉本地登录态——于是「看别人的文章结果把自己登出了」
 * 会真实发生，而且只在「有残留登录态 / 别人分享的链接直接打开」这类路径上复现。
 * 只测「能看到文章」是测不出这个 bug 的，必须连请求一起断言。
 */

const AUTHOR: AuthUser = {
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

function token(value: string): TokenPayload {
  return { access_token: value, token_type: 'bearer', expires_in: 3600 }
}

const POST: PostSummary = {
  id: '018f0000-0000-7000-8000-000000000010',
  author_id: AUTHOR.id,
  title: '第一篇',
  slug: 'first-post',
  summary: '尝试写点东西',
  cover_url: null,
  status: 'published',
  published_at: '2026-02-01T08:00:00Z',
  view_count: 7,
  tags: ['python'],
  created_at: '2026-01-31T08:00:00Z',
  updated_at: '2026-02-01T08:00:00Z',
}

function page(items: PostSummary[]) {
  return { items, total: items.length, offset: 0, limit: 10 }
}

/** 把调用过的 URL 收成可断言的字符串，省去每处 `String(input)`。 */
function requestedUrls(fetchMock: ReturnType<typeof installFetchMock>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input))
}

/**
 * 只把 `/…/posts` 这一个模板认作「公开列表」。
 *
 * 不能用 `includes('/posts')`：`/me/posts` 与 `/posts/{slug}` 都含这个子串，
 * 那样连「详情接口被误调」都会算成通过了。
 */
function isPublicList(url: string): boolean {
  return new URL(url, 'http://test.local').pathname.endsWith('/posts')
}

function renderPage(entry = '/posts') {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          {/* 必须走真实路由而不是直接渲染组件：标签、分页都是靠 URL 传的，
              绕过 Router 就把这页一半的行为测不到了 */}
          <Route path="/posts" element={<PostListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function login(codes: string[]) {
  setAuth(token('token-alice'), AUTHOR)
  return installFetchMock((url) => {
    if (url.endsWith('/auth/me/access'))
      return { data: { role_codes: [], permission_codes: codes } }
    if (url.endsWith('/auth/me')) return { data: AUTHOR }
    if (isPublicList(url)) return { data: page([POST]) }
    return { status: 404, code: 40400, message: '接口不存在' }
  })
}

describe('PostListPage 公开阅读', () => {
  it('游客能读到文章列表，且完全不碰 /auth/me 与 /auth/me/access', async () => {
    const fetchMock = installFetchMock((url) =>
      isPublicList(url)
        ? { data: page([POST]) }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderPage()

    expect(await screen.findByText('第一篇')).toBeInTheDocument()

    const urls = requestedUrls(fetchMock)
    expect(urls.some((url) => url.includes('/auth/me'))).toBe(false)

    // 游客不该看到只对登录用户有意义的入口
    expect(screen.queryByRole('link', { name: '写文章' })).toBeNull()
    expect(screen.queryByRole('link', { name: '我的文章' })).toBeNull()
  })

  it('登录但没有写权限时，只给「我的文章」，不给「写文章」', async () => {
    login(['post:update'])

    renderPage()

    expect(await screen.findByRole('link', { name: '我的文章' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '写文章' })).toBeNull()

    // 有权限点没匹配上时要说清楚缺什么，否则用户只看到「少了个按钮」
    expect(
      await screen.findByText('你没有「post:create」权限，因此看不到写文章的入口。'),
    ).toBeInTheDocument()
  })

  it('有 post:create 时放出「写文章」入口', async () => {
    login(['post:create'])

    renderPage()

    expect(await screen.findByRole('link', { name: '写文章' })).toBeInTheDocument()
  })

  it('点标签会用 tag 重新请求，且换标签时分页归零', async () => {
    const fetchMock = installFetchMock((url) =>
      isPublicList(url)
        ? { data: page([POST]) }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    // 从「第 2 页」这个状态进入，才能验证换标签时 offset 被清掉
    renderPage('/posts?offset=10')

    fireEvent.click(await screen.findByRole('link', { name: '#python' }))

    await waitFor(() => {
      const withTag = requestedUrls(fetchMock).filter((url) => url.includes('tag=python'))
      expect(withTag.length).toBeGreaterThan(0)
      // 留在第 2 页会导致「筛选后一条都没有」，而其实第一页就有。
      // 断言的是 offset=10 不再出现，而不是「没有 offset 参数」——
      // offset=0 是合法且期望的（0 不是空值，toQuery 不会把它丢掉）
      expect(withTag.every((url) => !url.includes('offset=10'))).toBe(true)
    })

    expect(await screen.findByText('清除')).toBeInTheDocument()
  })
})
