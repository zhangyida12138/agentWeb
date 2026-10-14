import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { createQueryClient } from '../../lib/query-client'
import { setAuth } from '../../stores/auth'
import { installFetchMock } from '../../test/api-mock'
import type { AuthUser, TokenPayload } from '../auth/types'

import { PostInteractionBar } from './PostInteractionBar'

/**
 * 文章互动条（点赞按钮 + 评论总数）的行为测试。
 *
 * 三条断言对应三个**只在特定路径上才会坏**的设计决定：
 *
 *   ① 游客也要能看到赞数。这个接口是公开的，若哪天有人给它加上
 *      `enabled: Boolean(token)`，游客看到的会是 0 —— 而 0 不是「加载中」，
 *      是一个看起来完全正常的错误数字，没人会去查。
 *
 *   ② 游客的按钮是**禁用**的，而不是隐藏的。隐藏会让「已经有 12 个赞」
 *      这件事也跟着消失，而赞数是公开信息。
 *
 *   ③ 点击之后的数字来自服务端响应。见下方那条故意返回 40 的 mock。
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

const POST_ID = '018f0000-0000-7000-8000-000000000010'

function token(value: string): TokenPayload {
  return { access_token: value, token_type: 'bearer', expires_in: 3600 }
}

function stats(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    post_id: POST_ID,
    like_count: 12,
    comment_count: 3,
    liked_by_me: false,
    ...overrides,
  }
}

function requestedUrls(fetchMock: ReturnType<typeof installFetchMock>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input))
}

function isStats(url: string): boolean {
  return new URL(url, 'http://test.local').pathname.endsWith('/interactions')
}

function renderBar(interactionsOpen = true) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <PostInteractionBar postId={POST_ID} interactionsOpen={interactionsOpen} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PostInteractionBar 游客', () => {
  it('能读到赞数与评论数，按钮禁用但不隐藏', async () => {
    const fetchMock = installFetchMock((url) =>
      isStats(url) ? { data: stats() } : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderBar()

    // 12 个赞是公开信息，游客必须看得到
    const likeButton = await screen.findByRole('button', { name: /赞 12/ })
    expect(likeButton).toBeInTheDocument()
    expect(likeButton).toBeDisabled()
    // 禁用原因要能被读屏软件读到，而不是只藏在 title 里
    expect(likeButton).toHaveAccessibleName('赞 12，登录后可点赞')

    expect(screen.getByText('评论 3 条')).toBeInTheDocument()

    // 关键：这个查询不该跟着 token 走，游客也要发出去
    expect(requestedUrls(fetchMock).some((url) => url.includes('/interactions'))).toBe(true)
    expect(requestedUrls(fetchMock).some((url) => url.includes('/auth/me'))).toBe(false)
  })
})

describe('PostInteractionBar 点赞', () => {
  it('赞数用服务端返回的值，不是本地 +1', async () => {
    setAuth(token('token-alice'), AUTHOR)
    const fetchMock = installFetchMock((url) => {
      if (url.endsWith('/auth/me/access'))
        return { data: { role_codes: [], permission_codes: ['like:toggle'] } }
      if (url.endsWith('/auth/me')) return { data: AUTHOR }
      if (url.endsWith('/likes/toggle')) {
        // 故意不回 13，而是回 40：就在这一点之间别处也有人点了赞。
        // 本地 +1 的实现会让下面「40」的断言失败——这正是这个用例存在的意义
        return { data: { target_type: 'post', target_id: POST_ID, liked: true, like_count: 40 } }
      }
      if (isStats(url)) return { data: stats() }
      return { status: 404, code: 40400, message: '接口不存在' }
    })

    renderBar()

    const likeButton = await screen.findByRole('button', { name: /赞 12/ })
    fireEvent.click(likeButton)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已赞 40/ })).toBeInTheDocument()
    })

    // 就地写缓存，不重新拉一次统计：点一下按钮不该产生第二次 GET
    const statsCalls = requestedUrls(fetchMock).filter((url) => isStats(url))
    expect(statsCalls).toHaveLength(1)
    // 评论数属于同一条缓存记录，不能被点赞顺手清成 0
    expect(screen.getByText('评论 3 条')).toBeInTheDocument()
  })

  it('没权限时不发请求，并说明缺哪个权限点', async () => {
    setAuth(token('token-alice'), AUTHOR)
    const fetchMock = installFetchMock((url) => {
      if (url.endsWith('/auth/me/access'))
        // 登录了，但角色里没有 like:toggle
        return { data: { role_codes: ['reader'], permission_codes: [] } }
      if (url.endsWith('/auth/me')) return { data: AUTHOR }
      if (isStats(url)) return { data: stats() }
      return { status: 404, code: 40400, message: '接口不存在' }
    })

    renderBar()

    const likeButton = await screen.findByRole('button', { name: /赞 12/ })
    await waitFor(() => expect(likeButton).toBeDisabled())
    expect(likeButton).toHaveAccessibleName('赞 12，你没有「like:toggle」权限')

    fireEvent.click(likeButton)
    expect(requestedUrls(fetchMock).some((url) => url.includes('/likes/toggle'))).toBe(false)
  })

  it('文章已下架时不发请求（后端会回 40940）', async () => {
    setAuth(token('token-alice'), AUTHOR)
    const fetchMock = installFetchMock((url) => {
      if (url.endsWith('/auth/me/access'))
        return { data: { role_codes: ['reader'], permission_codes: ['like:toggle'] } }
      if (url.endsWith('/auth/me')) return { data: AUTHOR }
      if (isStats(url)) return { data: stats() }
      return { status: 404, code: 40400, message: '接口不存在' }
    })

    renderBar(false)

    const likeButton = await screen.findByRole('button', { name: /赞 12/ })
    await waitFor(() => expect(likeButton).toBeDisabled())
    // 已下架只是不能再加赞，已有的赞数照常显示
    expect(likeButton).toHaveAccessibleName('赞 12，文章已下架，不再接受新的点赞')

    fireEvent.click(likeButton)
    expect(requestedUrls(fetchMock).some((url) => url.includes('/likes/toggle'))).toBe(false)
  })
})
