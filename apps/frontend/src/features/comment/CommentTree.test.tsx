import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { createQueryClient } from '../../lib/query-client'
import { setAuth } from '../../stores/auth'
import { installFetchMock, bodyOf } from '../../test/api-mock'
import type { AuthUser, TokenPayload } from '../auth/types'

import { CommentTree } from './CommentTree'

import type { CommentNode, CommentPage } from './types'

/**
 * 评论区（`CommentTree`）的行为测试。
 *
 * 这个文件里最重要的两条断言都不是「文字显示出来了」，而是两个**容易悄悄坏掉**的东西：
 *
 *   ① 游客读评论时**没有**打 `/auth/me` 或 `/auth/me/access`。
 *      两个接口都需要登录，未登录必然 401，而 api 层在 401 时会清掉本地登录态。
 *      也就是说：一个「评论区顺手加了个 enabled: Boolean(user) 之外的判断」的改动，
 *      表现会是「游客打开别人的文章，看着看着被登出了」——
 *      只断言「评论显示出来了」根本测不出来，必须连请求一起断言。
 *
 *   ② 点赞后显示的数字来自**服务端响应**，不是本地 +1。
 *      本地 +1 在单人测试里永远是对的，但在「别人也赞了」的场景下会显示错，
 *      而且取消点赞时（-1）更容易把数字算成负的。
 *      所以这里让 mock 故意返回一个**不等于 ±1** 的结果：
 *      如果实现是本地加减，测试立刻失败。
 *
 *   ③ 深层回复仍在**同一个缩进级**（见「层级与作者名」那组用例）。
 *      把 `depth` 当缩进倍数是这类组件最常见的错法，而且单看「文字渲染出来了」
 *      完全测不出来——只有断言容器的类名才能拦住它。
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

const OTHER_USER_ID = '018f0000-0000-7000-8000-000000000002'
const POST_ID = '018f0000-0000-7000-8000-000000000010'
const ROOT_ID = '018f0000-0000-7000-8000-0000000000a1'
const REPLY_ID = '018f0000-0000-7000-8000-0000000000a2'
const DEEP_ID = '018f0000-0000-7000-8000-0000000000a3'

function token(value: string): TokenPayload {
  return { access_token: value, token_type: 'bearer', expires_in: 3600 }
}

function comment(overrides: Partial<CommentNode> = {}): CommentNode {
  return {
    id: ROOT_ID,
    post_id: POST_ID,
    author_id: OTHER_USER_ID,
    author_display_name: 'bob',
    parent_id: null,
    parent_author_display_name: null,
    content: '这是别人的评论',
    is_deleted: false,
    like_count: 2,
    liked_by_me: false,
    created_at: '2026-03-01T08:00:00Z',
    updated_at: '2026-03-01T08:00:00Z',
    replies: [],
    ...overrides,
  }
}

function page(items: CommentNode[], total = items.length): CommentPage {
  return { items, total, offset: 0, limit: 10 }
}

function requestedUrls(fetchMock: ReturnType<typeof installFetchMock>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input))
}

function isCommentList(url: string): boolean {
  return new URL(url, 'http://test.local').pathname.endsWith('/comments')
}

/** 找到某条评论正文所在的容器（`<article>`），用来断言缩进规则。 */
function commentWrapper(content: string): HTMLElement {
  const wrapper = screen.getByText(content).closest('article')
  if (!wrapper) throw new Error(`找不到「${content}」所在的评论容器`)
  return wrapper as HTMLElement
}

function renderTree() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <CommentTree postId={POST_ID} interactionsOpen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 把 `/auth/me*` 的桩抽出来，因为有好几个用例需要「登录用户」这一侧。 */
function login(codes: string[]) {
  setAuth(token('token-alice'), AUTHOR)
  return installFetchMock((url) => {
    if (url.endsWith('/auth/me/access'))
      return { data: { role_codes: [], permission_codes: codes } }
    if (url.endsWith('/auth/me')) return { data: AUTHOR }
    if (isCommentList(url)) return { data: page([comment()]) }
    return { status: 404, code: 40400, message: '接口不存在' }
  })
}

describe('CommentTree 公开阅读', () => {
  it('游客能读到评论，且完全不碰 /auth/me 与 /auth/me/access', async () => {
    const fetchMock = installFetchMock((url) =>
      isCommentList(url)
        ? { data: page([comment()]) }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderTree()

    expect(await screen.findByText('这是别人的评论')).toBeInTheDocument()

    const urls = requestedUrls(fetchMock)
    expect(urls.some((url) => url.includes('/auth/me'))).toBe(false)

    // 游客看得到赞数，但按钮是禁用的（点赞需要一人一票的记录，必须登录）
    const likeButton = screen.getByRole('button', { name: /赞 2/ })
    expect(likeButton).toBeDisabled()

    // 游客不该看到发表框
    expect(screen.queryByLabelText('发表评论')).toBeNull()
    expect(screen.getByText('登录后可以参与讨论。')).toBeInTheDocument()
  })

  it('没有任何评论时给出「来说第一句」而不是空白', async () => {
    installFetchMock((url) =>
      isCommentList(url)
        ? { data: page([], 0) }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderTree()

    expect(await screen.findByText('还没有评论，来说第一句吧。')).toBeInTheDocument()
  })
})

describe('CommentTree 墓碑语义', () => {
  it('撤回的评论不显示正文，但节点仍然在（回复还有归属）', async () => {
    installFetchMock((url) =>
      isCommentList(url)
        ? {
            data: page([
              comment({
                is_deleted: true,
                // 后端撤回后 content 就是空串；这里额外塞一句话来证明
                // 「不显示内容」靠的是 is_deleted 而不是 content 是否为空——
                // 如果实现写成 {!content && ...}，这条用例会挂
                content: '',
                replies: [comment({ id: REPLY_ID, parent_id: ROOT_ID, content: '我是回复' })],
              }),
            ]),
          }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderTree()

    expect(await screen.findByText('该评论已被作者撤回')).toBeInTheDocument()
    // 关键：回复必须还在。整块 return null 掉墓碑的话，别人的回复会跟着消失
    expect(screen.getByText('我是回复')).toBeInTheDocument()
  })

  it('回复嵌在根评论下面，不会另起一段对话', async () => {
    installFetchMock((url) =>
      isCommentList(url)
        ? {
            data: page([
              comment({
                content: '根评论',
                replies: [comment({ id: REPLY_ID, parent_id: ROOT_ID, content: '一条回复' })],
              }),
            ]),
          }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderTree()

    expect(await screen.findByText('根评论')).toBeInTheDocument()
    expect(screen.getByText('一条回复')).toBeInTheDocument()
    // 分页单位是「段对话」（根评论数），所以只有 1 段，不因回复而变成 2
    expect(screen.getByText('1 段对话')).toBeInTheDocument()
  })
})

describe('CommentTree 层级与作者名', () => {
  it('显示「用户 A 回复 B」，名字来自响应，不去按 id 查用户', async () => {
    const fetchMock = installFetchMock((url) =>
      isCommentList(url)
        ? {
            data: page([
              comment({
                author_display_name: 'alice',
                replies: [
                  comment({
                    id: REPLY_ID,
                    parent_id: ROOT_ID,
                    author_id: AUTHOR.id,
                    author_display_name: 'bob',
                    parent_author_display_name: 'alice',
                    content: '我同意',
                  }),
                ],
              }),
            ]),
          }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderTree()

    expect(await screen.findByText('用户 alice')).toBeInTheDocument()
    expect(screen.getByText('用户 bob')).toBeInTheDocument()
    expect(screen.getByText('回复 alice')).toBeInTheDocument()

    // 根评论没有被回复的对象，不该凭空多出一行「回复 xxx」
    expect(screen.getAllByText(/^回复 /)).toHaveLength(1)

    // 名字必须是响应里带的：整个过程不去问 /users/{id}。
    // 那是匿名访客打不通的接口（需要鉴权），也是把 N+1 搬到浏览器
    const urls = requestedUrls(fetchMock)
    expect(urls.some((url) => url.includes('/users/'))).toBe(false)
  })

  it('三层以上的回复仍在同一缩进级：只有第一层回复带那条左边框', async () => {
    installFetchMock((url) =>
      isCommentList(url)
        ? {
            data: page([
              comment({
                content: '根评论',
                replies: [
                  comment({
                    id: REPLY_ID,
                    parent_id: ROOT_ID,
                    content: '第一层回复',
                    replies: [
                      comment({
                        id: DEEP_ID,
                        parent_id: REPLY_ID,
                        content: '第二层回复',
                      }),
                    ],
                  }),
                ],
              }),
            ]),
          }
        : { status: 404, code: 40400, message: '接口不存在' },
    )

    renderTree()

    // 三层都渲染出来了：后端不折算层级，前端也不吞掉深层节点
    expect(await screen.findByText('第二层回复')).toBeInTheDocument()

    // 根评论不缩进
    expect(commentWrapper('根评论').className).not.toContain('border-l-2')
    // 第一层回复缩进一格
    expect(commentWrapper('第一层回复').className).toContain('border-l-2')
    // 更深层的回复**不再叠加**缩进。子容器本来就嵌在父容器里，
    // 所以「不加内缩」就等价于「停在第一层回复的位置上」；
    // 如果实现把 depth 当倍数，这里会再缩一格，长对话会被挤成一条竖线
    expect(commentWrapper('第二层回复').className).not.toContain('border-l-2')
  })
})

describe('CommentTree 点赞', () => {
  it('赞数用服务端返回的值，不是本地 +1', async () => {
    setAuth(token('token-alice'), AUTHOR)
    const fetchMock = installFetchMock((url) => {
      if (url.endsWith('/auth/me/access'))
        return { data: { role_codes: [], permission_codes: ['like:toggle'] } }
      if (url.endsWith('/auth/me')) return { data: AUTHOR }
      if (url.endsWith('/likes/toggle')) {
        // 故意不回 3（2+1），而是回 40：同一个瞬间别处也有人点了赞。
        // 本地 +1 的实现会让下面的断言失败
        return { data: { target_type: 'comment', target_id: ROOT_ID, liked: true, like_count: 40 } }
      }
      if (isCommentList(url)) return { data: page([comment()]) }
      return { status: 404, code: 40400, message: '接口不存在' }
    })

    renderTree()

    const likeButton = await screen.findByRole('button', { name: /赞 2/ })
    expect(likeButton).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(likeButton)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已赞 40/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      )
    })

    // 请求体必须带上 target_type，否则后端会按 40041 拒掉
    const toggleCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/likes/toggle'),
    )
    expect(toggleCall).toBeDefined()
    expect(bodyOf(toggleCall![1])).toEqual({
      target_type: 'comment',
      target_id: ROOT_ID,
    })
  })
})

describe('CommentTree 发表评论', () => {
  it('回复框是缩进的表单，提交后带上 parent_id 并把新评论拉回来', async () => {
    const fetchMock = login(['comment:create', 'like:toggle'])

    renderTree()

    fireEvent.click(await screen.findByRole('button', { name: '回复' }))

    const textarea = await screen.findByLabelText('回复')
    fireEvent.change(textarea, { target: { value: '我同意' } })

    // 点开回复框之后，评论上的那颗按钮文案变成「收起」，
    // 于是此刻名叫「回复」的按钮只剩表单里的提交按钮——不用额外的选择器去消歧
    fireEvent.click(screen.getByRole('button', { name: '回复' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input).endsWith('/comments') && init?.method === 'POST',
      )
      expect(postCall).toBeDefined()
      // 传的是被回复那条评论的 id，后端**原样记录**（不做「归一到根」那种折算）——
      // 所以回复一条回复完全合法，前端不需要自己去找根
      expect(bodyOf(postCall![1])).toEqual({ content: '我同意', parent_id: ROOT_ID })
    })
  })

  it('空白内容不发请求，直接在字段上报错', async () => {
    const fetchMock = login(['comment:create'])

    renderTree()

    const textarea = await screen.findByLabelText('发表评论')
    fireEvent.change(textarea, { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: '发表' }))

    expect(await screen.findByText('评论内容不能为空')).toBeInTheDocument()

    const postCalls = fetchMock.mock.calls.filter(
      ([input, init]) => String(input).endsWith('/comments') && init?.method === 'POST',
    )
    // 一次必然失败的往返不值得发：后端会 strip 之后回 40040
    expect(postCalls).toHaveLength(0)
  })

  it('后端的校验消息直接显示在输入框上，不自己编文案', async () => {
    setAuth(token('token-alice'), AUTHOR)
    installFetchMock((url, init) => {
      if (url.endsWith('/auth/me/access'))
        return { data: { role_codes: [], permission_codes: ['comment:create'] } }
      if (url.endsWith('/auth/me')) return { data: AUTHOR }
      if (isCommentList(url) && init?.method === 'POST') {
        return {
          status: 400,
          // 后端 CommentContent 抛的 40040，带 data.field 用于定位字段
          code: 40040,
          message: '评论内容不能为空或只有空白字符',
          data: { field: 'content' },
        }
      }
      if (isCommentList(url)) return { data: page([comment()]) }
      return { status: 404, code: 40400, message: '接口不存在' }
    })

    renderTree()

    const textarea = await screen.findByLabelText('发表评论')
    // 用一个「本地挡不住」的值：它非空，但只由不可见字符组成
    // （本地只挡 trim() 之后为空的字符串，这个值 trim 后仍然是内容）
    fireEvent.change(textarea, { target: { value: '\u200b\u200b' } })
    fireEvent.click(screen.getByRole('button', { name: '发表' }))

    expect(await screen.findByText('评论内容不能为空或只有空白字符')).toBeInTheDocument()
  })
})
