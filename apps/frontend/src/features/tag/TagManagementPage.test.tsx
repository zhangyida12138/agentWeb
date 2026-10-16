import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { createQueryClient } from '../../lib/query-client'
import { setAuth } from '../../stores/auth'
import { bodyOf, installFetchMock } from '../../test/api-mock'
import type { AuthUser, TokenPayload } from '../auth/types'

import { TagManagementPage } from './TagManagementPage'

import type { Tag, TagPage } from './types'

/**
 * 「标签管理」——管理员维度的标签管理。
 *
 * 与 MyTagsPage 的测试是互补的两半，各自钉住"维度"的一个面：
 *   那边钉**范围**（author_id 必须是我），这边钉**动作**（新建 / 下架 / 恢复 / 删除）。
 *
 * 最要紧的一条是第一个用例的**否定**断言：
 *   没有 `tag:manage` 时不但不显示表格，而且**一个 /tags 请求都不发**。
 *   写成"发出去、拿到 403、显示错误"在功能上完全一样，但那会把一个
 *   必然失败的往返变成用户看到的第一印象——先闪一下报错再被守卫弹走。
 *
 * 另外两个容易被漏掉的点：
 *   · 「恢复」和「下架」是**同一条** PATCH /tags/{id}/status，只是 status 不同；
 *     恢复已删除的标签也走它（后端刻意在那条路径上不检查"是否已删除"）。
 *   · 恢复之后那一行会从当前（已删除）tab 里消失，所以必须有文案说明它去哪了，
 *     否则看起来像"点一下把它点没了"。
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

const TAG_MANAGE = 'tag:manage'

function token(value: string): TokenPayload {
  return { access_token: value, token_type: 'bearer', expires_in: 3600 }
}

function tag(overrides: Partial<Tag> & Pick<Tag, 'id' | 'name'>): Tag {
  return {
    slug: overrides.name,
    description: null,
    status: 'normal',
    type: 'user',
    author_id: null,
    post_count: 0,
    ...overrides,
  }
}

const NORMAL = tag({ id: 'tag-normal', name: '机器学习', post_count: 3 })
const OFFICIAL = tag({ id: 'tag-official', name: '公告', type: 'system' })
const DELETED = tag({ id: 'tag-deleted', name: '临时草稿', status: 'deleted' })

function page(items: Tag[]): TagPage {
  return { items, total: items.length, offset: 0, limit: 20 }
}

interface Reply {
  status?: number
  code?: number
  message?: string
  data?: unknown
}

function isTagList(url: string): boolean {
  return new URL(url, 'http://test.local').pathname.endsWith('/tags')
}

function tagListCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) => isTagList(String(input)))
}

function callWith(fetchMock: ReturnType<typeof installFetchMock>, method: string) {
  return fetchMock.mock.calls.find(
    ([, init]) => (init as RequestInit | undefined)?.method === method,
  )
}

/**
 * 打桩。
 *
 * `codes` 是唯一的开关：`tag:manage` 在不在，决定了这一页是"内容"还是"缺权限提示"。
 * 列表按当前请求的 status 返回对应的那一档，这样"点 tab 换档"在断言里能看见变化。
 */
function setup(codes: string[], items: Tag[] = [NORMAL, OFFICIAL]) {
  setAuth(token('token-admin'), ADMIN)
  return installFetchMock((url, init) => {
    if (url.endsWith('/auth/me/access')) {
      return { data: { role_codes: [], permission_codes: codes } }
    }
    if (url.endsWith('/auth/me')) return { data: ADMIN }

    if (isTagList(url)) {
      // 新建也打同一个集合地址，靠 method 区分——否则会把创建结果当成一页列表返回，
      // 而 mutation 拿到的对象形状就错了（不会报错，只会静静地用错数据）
      if ((init as RequestInit | undefined)?.method === 'POST') return { data: NORMAL }
      const status = new URL(url, 'http://test.local').searchParams.get('status')
      if (status === 'deleted') return { data: page([DELETED]) }
      return { data: page(items) }
    }

    // 状态变更：回显改过之后的对象，供"恢复后提示"那句文案取值
    if (url.includes('/status')) {
      const body = bodyOf(init as RequestInit | undefined) as { status?: string } | undefined
      return { data: { ...DELETED, status: body?.status ?? 'normal' } }
    }

    if (url.includes('/tags/')) {
      const method = (init as RequestInit | undefined)?.method
      // DELETE 回 204、没有 body——按 lib/api.ts 的约定应当回 undefined
      if (method === 'DELETE') return { status: 204 }
      return { data: NORMAL }
    }

    return { status: 404, code: 40400, message: '接口不存在' } satisfies Reply
  })
}

function renderPage(entry = '/admin/tags') {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/admin/tags" element={<TagManagementPage />} />
          {/* 缺权限提示里有一个指向「我的标签」的链接，得给它一个落点，
              否则 react-router 会因为找不到路由而报警告、断言也被噪音污染 */}
          <Route path="/my/tags" element={<p>我的标签占位</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TagManagementPage 管理员维度', () => {
  it('管理员看到全站列表、类型/创建者列与治理动作', async () => {
    setup([TAG_MANAGE])

    renderPage()

    expect(await screen.findByText('机器学习')).toBeInTheDocument()

    // 治理列只在这一维露出：作者看到 uuid 只会困惑
    expect(screen.getByRole('columnheader', { name: '类型' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '创建者' })).toBeInTheDocument()

    // 官方标签是 `system`，作者那一页根本不显示这一列。
    // 必须在表格内查：类型筛选里也有一个叫「官方」的按钮，
    // 全局查会命中两个元素——那是个假失败，而不是真的重了
    expect(within(screen.getByRole('table')).getByText('官方')).toBeInTheDocument()

    expect(screen.getByRole('button', { name: '新建标签' })).toBeInTheDocument()
    // 未删除的行有下架 + 删除；系统标签也能被下架（它是治理动作，与归属无关）
    expect(screen.getAllByRole('button', { name: '下架' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: '删除' })).toHaveLength(2)
  })

  it('没有 tag:manage 时不渲染表格，且一个 /tags 请求都不发', async () => {
    const fetchMock = setup(['post:create'])

    renderPage()

    // 提示必须点名缺哪个权限码：只说"没有权限"会让用户去猜、
    // 或者干脆以为是系统坏了
    expect(await screen.findByText(new RegExp(TAG_MANAGE))).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建标签' })).not.toBeInTheDocument()

    // 关键：不是"请求失败后隐藏"，而是压根没请求
    expect(tagListCalls(fetchMock)).toHaveLength(0)
  })

  it('缺权限时给出回到「我的标签」的出口', async () => {
    setup(['post:create'])

    renderPage()

    // 这一页对他没用，但他想干的事（整理自己建的标签）在另一页上是合法的。
    // 不给这个链接，他只会觉得"标签功能整个没开"
    const link = await screen.findByRole('link', { name: '我的标签' })
    expect(link).toHaveAttribute('href', '/my/tags')
  })

  it('新建标签：空描述提交成 null，类型跟着选择走', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage()
    await screen.findByText('机器学习')

    fireEvent.click(screen.getByRole('button', { name: '新建标签' }))
    await screen.findByRole('dialog')

    fireEvent.change(await screen.findByLabelText('标签名'), {
      target: { value: '  向量数据库  ' },
    })
    fireEvent.change(screen.getByLabelText('类型'), { target: { value: 'system' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    const postCall = callWith(fetchMock, 'POST')
    expect(String(postCall?.[0])).toContain('/tags')
    expect(bodyOf(postCall?.[1] as RequestInit | undefined)).toEqual({
      // 前后空白必须去掉：后端 `TagName` 建的 slug 会把空格转成连字符，
      // 带着空白提交会得到一个看起来一样的名字配着一个不一样的 slug
      name: '向量数据库',
      description: null,
      type: 'system',
    })
  })

  it('前端先拦住非法的标签名，不发这次注定失败的往返', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage()
    await screen.findByText('机器学习')

    fireEvent.click(screen.getByRole('button', { name: '新建标签' }))
    await screen.findByRole('dialog')

    // `#` 是后端 `_TAG_RE` 明确禁止的字符（会与 URL 锚点冲突），
    // 前端的正则与后端逐字对齐，所以这里能就地拦下
    fireEvent.change(await screen.findByLabelText('标签名'), { target: { value: 'c#' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))

    await waitFor(() => {
      expect(screen.getByLabelText('标签名')).toHaveAttribute('aria-invalid', 'true')
    })
    expect(callWith(fetchMock, 'POST')).toBeUndefined()
    // 失败时弹窗留着，用户能直接改那个字
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('下架走 PATCH /tags/{id}/status', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage()
    await screen.findByText('机器学习')

    fireEvent.click(screen.getAllByRole('button', { name: '下架' })[0])

    await waitFor(() => {
      expect(callWith(fetchMock, 'PATCH')).toBeDefined()
    })

    const patchCall = callWith(fetchMock, 'PATCH')
    expect(String(patchCall?.[0])).toContain(`/tags/${NORMAL.id}/status`)
    expect(bodyOf(patchCall?.[1] as RequestInit | undefined)).toEqual({ status: 'abnormal' })
  })

  it('在「已删除」档里，那一行的操作是「恢复」而不是「删除」', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage('/admin/tags?status=deleted')

    expect(await screen.findByText('临时草稿')).toBeInTheDocument()

    // 这一行的 status 是 deleted，所以没有「删除」按钮（DELETE 幂等，但按钮会误导），
    // 也没有「编辑」（后端对已删除的标签回 404，不是"没权限"）
    expect(screen.queryByRole('button', { name: '删除' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '恢复' }))

    await waitFor(() => {
      expect(callWith(fetchMock, 'PATCH')).toBeDefined()
    })

    // 恢复已删除的标签走的**就是**同一条 PATCH /status
    // （后端 ChangeTagStatusUseCase 刻意不调 ensure_not_deleted）
    const patchCall = callWith(fetchMock, 'PATCH')
    expect(String(patchCall?.[0])).toContain(`/tags/${DELETED.id}/status`)
    expect(bodyOf(patchCall?.[1] as RequestInit | undefined)).toEqual({ status: 'normal' })

    // 恢复之后它就从当前这一档消失了。没有这句说明，看起来像"点一下把它点没了"
    expect(await screen.findByText(/已恢复为「正常」/)).toBeInTheDocument()
  })

  it('删除要二次确认，确认后发 DELETE', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage()
    await screen.findByText('机器学习')

    fireEvent.click(screen.getAllByRole('button', { name: '删除' })[0])
    await screen.findByRole('dialog')

    // 确认框必须说清"无法从界面恢复"，否则管理员会把它当成可撤销的下架
    expect(screen.getByText(/无法从界面恢复/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    const deleteCall = callWith(fetchMock, 'DELETE')
    expect(String(deleteCall?.[0])).toContain(`/tags/${NORMAL.id}`)
    // DELETE 不带 body，后端回 204
    expect((deleteCall?.[1] as RequestInit | undefined)?.body).toBeUndefined()
  })

  it('类型筛选走 ?type=system，且切换时清掉 offset', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage('/admin/tags?offset=20')
    await screen.findByText('机器学习')

    fireEvent.click(screen.getByRole('button', { name: '官方' }))

    await waitFor(() => {
      expect(tagListCalls(fetchMock)).toHaveLength(2)
    })

    const next = new URL(String(tagListCalls(fetchMock)[1][0]), 'http://test.local')
    expect(next.searchParams.get('type')).toBe('system')
    // 与状态档位同一条规则：换筛选必须回第一页。
    // 断言 `'0'` 而不是 `null`：0 是合法取值，`toQuery` 只丢 undefined 与空串
    expect(next.searchParams.get('offset')).toBe('0')
  })

  it('「全部类型」不发 type 参数（后端把"不传"定义为不筛）', async () => {
    const fetchMock = setup([TAG_MANAGE])

    renderPage('/admin/tags?type=system')
    await screen.findByText('机器学习')

    fireEvent.click(screen.getByRole('button', { name: '全部类型' }))

    await waitFor(() => {
      expect(tagListCalls(fetchMock)).toHaveLength(2)
    })

    const next = new URL(String(tagListCalls(fetchMock)[1][0]), 'http://test.local')
    // 空串在这里是**错的**：`?type=` 会被后端的 `TagType.parse("")` 判成非法。
    // "不筛"的唯一正确表达是不带这个参数
    expect(next.searchParams.has('type')).toBe(false)
  })
})
