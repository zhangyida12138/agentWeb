import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { createQueryClient } from '../../lib/query-client'
import { setAuth } from '../../stores/auth'
import { bodyOf, installFetchMock } from '../../test/api-mock'
import type { AuthUser, TokenPayload } from '../auth/types'

import { MyTagsPage } from './MyTagsPage'

import type { Tag, TagPage } from './types'

/**
 * 「我的标签」——作者维度的标签管理。
 *
 * 这里要钉住的是**范围**这件事，而不是"表格渲染出来了"：
 *   ① 请求必须带 `author_id = 我`。漏了它页面上看不出任何异常，
 *      只是列表里静静地多了别人的标签——最难发现的一类 bug。
 *   ② 别人的 / 无主的 / 官方的标签，行上不能出现「编辑」。
 *      `canEditTag` 本身在 permissions.test.ts 里已经矩阵化了，
 *      这里只验"表格真的按行去问了它"，而不是按页统一开了一遍。
 *   ③ 没有 user 时**一次 /tags 都不请求**。`author_id` 缺失在后端等于"不筛"，
 *      所以这个 `enabled` 是页面上唯一挡住"看到全站标签"的那道闸，
 *      而不是一个可有可无的加载优化。
 *   ④ 后端把"名字格式非法"报在 `tag_names` 这个字段上（文章那条链路的遗留），
 *      前端必须把它映射到名称输入框——落到弹窗顶部的话，
 *      用户会以为是自己没权限。
 */

const ALICE: AuthUser = {
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

const BOB_ID = '018f0000-0000-7000-8000-000000000002'

function token(value: string): TokenPayload {
  return { access_token: value, token_type: 'bearer', expires_in: 3600 }
}

function tag(overrides: Partial<Tag> & Pick<Tag, 'id' | 'name'>): Tag {
  return {
    slug: overrides.name,
    description: null,
    status: 'normal',
    type: 'user',
    author_id: ALICE.id,
    post_count: 0,
    ...overrides,
  }
}

/** 我建的。 */
const MINE = tag({ id: 'tag-mine', name: '机器学习', description: '模型、训练与评测' })
/** 别人建的：后端也返回它（按 author_id 过滤是后端的事），用来验证行级权限。 */
const OTHERS = tag({ id: 'tag-others', name: '前端', author_id: BOB_ID })
/** 无主的：author_id 为 null，只有管理员能处置。 */
const ORPHAN = tag({ id: 'tag-orphan', name: '旧笔记', author_id: null })
/** 官方的：作者即便看到也不能改。 */
const OFFICIAL = tag({ id: 'tag-official', name: '公告', type: 'system', author_id: null })

const ALL = [MINE, OTHERS, ORPHAN, OFFICIAL]

function page(items: Tag[], offset = 0): TagPage {
  return { items, total: items.length, offset, limit: 20 }
}

/**
 * 打桩返回值的形状。
 *
 * 自己写一份而不从 `test/api-mock` 里导出：那个模块只导了 `installFetchMock`
 * 与 `bodyOf`，多导一个类型出来为了这个文件省两行，不划算。
 */
interface Reply {
  status?: number
  code?: number
  message?: string
  data?: unknown
}

function requestedUrls(fetchMock: ReturnType<typeof installFetchMock>): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input))
}

/**
 * 只要 `/tags` 这一个集合地址（不含 `/tags/{id}` 这类派生路径）。
 *
 * 用 `pathname.endsWith('/tags')` 而不是 `=== '/tags'`：`lib/api.ts` 会拼上
 * `API_BASE = '/api/v1'`，真实路径是 `/api/v1/tags`。写成全等会静默地把
 * 列表请求判给兜底的 404 分支，于是所有用例都卡在"列表加载不出来"上。
 */
function isTagList(url: string): boolean {
  return new URL(url, 'http://test.local').pathname.endsWith('/tags')
}

function tagListCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) => isTagList(String(input)))
}

/**
 * 登录态的桩。
 *
 * 权限码默认为空数组：作者这一维**不靠权限码**，靠 `author_id`。
 * 传 `codes` 是为了覆盖"作者恰好也是管理员"的情况——那时页面上该多出治理入口。
 *
 * `override` 先于所有默认分支被问一次，返回 `undefined` 表示"这个 URL 我不管"：
 * 只在某一个用例里改某一条接口的返回值时用它，不必把整套桩再抄一遍。
 */
function login(codes: string[], override?: (url: string) => Reply | undefined) {
  setAuth(token('token-alice'), ALICE)
  return installFetchMock((url) => {
    const custom = override?.(url)
    if (custom) return custom
    if (url.endsWith('/auth/me/access'))
      return { data: { role_codes: [], permission_codes: codes } }
    if (url.endsWith('/auth/me')) return { data: ALICE }
    if (isTagList(url)) return { data: page(ALL) }
    if (url.includes('/tags/')) return { data: MINE }
    return { status: 404, code: 40400, message: '接口不存在' }
  })
}

function renderPage(entry = '/my/tags') {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          {/* 走真实路由：status / keyword / offset 都靠 URL 传，
              直接渲染组件会把这一页一半的行为测不到 */}
          <Route path="/my/tags" element={<MyTagsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MyTagsPage 作者维度', () => {
  it('列表请求带上 author_id = 我，并且只给我建的标签开编辑入口', async () => {
    const fetchMock = login([])

    renderPage()

    expect(await screen.findByText('机器学习')).toBeInTheDocument()

    // ① 范围：没有 author_id 的话后端会返回全站标签，而界面上看不出任何区别
    const [listCall] = tagListCalls(fetchMock)
    const listUrl = new URL(String(listCall[0]), 'http://test.local')
    expect(listUrl.searchParams.get('author_id')).toBe(ALICE.id)
    // 缺省档位是 normal，且由前端显式声明（不依赖后端默认，否则 tab 会高亮错一项）
    expect(listUrl.searchParams.get('status')).toBe('normal')
    expect(listUrl.searchParams.get('limit')).toBe('20')

    // ② 行级权限：四行里只有第一行是可编辑的。
    // 别人的（40350）、无主的（40350）、官方的（40051）都不能给按钮
    expect(screen.getAllByRole('button', { name: '编辑' })).toHaveLength(1)

    // 作者维度没有治理动作——一个都不该出现
    expect(screen.queryByRole('button', { name: '下架' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建标签' })).not.toBeInTheDocument()
  })

  it('普通作者看不到「标签管理」入口，管理员才看得到', async () => {
    login([])
    const { unmount } = renderPage()
    await screen.findByText('机器学习')
    expect(screen.queryByRole('link', { name: '标签管理' })).not.toBeInTheDocument()
    unmount()

    login(['tag:manage'])
    renderPage()
    expect(await screen.findByRole('link', { name: '标签管理' })).toBeInTheDocument()
  })

  it('切换状态档位时会清掉 offset', async () => {
    const fetchMock = login([])

    // 从"第 2 页 + 正常档"进：这是最常见的真实入口（改完一个返回列表）
    renderPage('/my/tags?status=normal&offset=20')

    await screen.findByText('机器学习')
    expect(
      new URL(String(tagListCalls(fetchMock)[0][0]), 'http://test.local').searchParams.get(
        'offset',
      ),
    ).toBe('20')

    fireEvent.click(screen.getByRole('button', { name: '已删除' }))

    await waitFor(() => {
      expect(tagListCalls(fetchMock)).toHaveLength(2)
    })

    // 关键：offset 必须回到第一页。
    // 停在"已删除档的第 2 页"是空页——那一档通常一共就一两条，
    // 于是用户看到的是"筛完之后什么都没有"
    //
    // 断言写 `'0'` 而不是 `null`：后端确实把"不传 offset"当 0，
    // 但 `toQuery` 只丢 `undefined` 与空串，0 是合法取值（第一页）。
    // 要求 URL 上真的没有这个参数，等于要求实现把 0 也当成"没传"，
    // 那会让"第一页"和"不关心"在请求上长得一模一样。
    const next = new URL(String(tagListCalls(fetchMock)[1][0]), 'http://test.local')
    expect(next.searchParams.get('status')).toBe('deleted')
    expect(next.searchParams.get('offset')).toBe('0')
  })

  it('没有登录用户时一次标签请求都不发', async () => {
    // 不给 setAuth：token 与 user 都是空的。
    // 这时 author_id 会是 undefined，后端把它当"不筛"→ 返回全站标签。
    // 所以这一页宁可不发请求（enabled: Boolean(user?.id)），
    // 而这条断言正是那个 enabled 的守卫
    const fetchMock = installFetchMock(() => ({ status: 404, code: 40400, message: '接口不存在' }))

    renderPage()

    // 先等页面真的跑起来（权限请求已经发出去），再断言标签列表一个请求都没有。
    // 不等的话可能只是"还没来得及发"，那样的通过是没有意义的
    await waitFor(() => {
      expect(requestedUrls(fetchMock).some((url) => url.includes('/auth/me/access'))).toBe(true)
    })

    expect(tagListCalls(fetchMock)).toHaveLength(0)
  })

  it('改名走 PUT /tags/{id}，重名时错误挂到名称输入框而不是弹窗顶部', async () => {
    const fetchMock = login([], (url) =>
      url.includes('/tags/')
        ? // 40950 = TagAlreadyExistsError，后端把这个错误的 field 标成 `name`
          { status: 409, code: 40950, message: '标签名已被占用', data: { field: 'name' } }
        : undefined,
    )

    renderPage()
    await screen.findByText('机器学习')

    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    await screen.findByRole('dialog')

    // 编辑弹窗必须回填当前值，否则用户以为要重新打一遍
    const nameInput = await screen.findByLabelText('标签名')
    expect(nameInput).toHaveValue('机器学习')

    fireEvent.change(nameInput, { target: { value: '机器学习基础' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    // 错误挂在输入框上（aria-invalid），而不是弹窗顶部的整表错误：
    // 否则用户会去怀疑权限，而不是去看那个名字
    await waitFor(() => {
      expect(screen.getByLabelText('标签名')).toHaveAttribute('aria-invalid', 'true')
    })
    expect(screen.getByText('标签名已被占用')).toBeInTheDocument()

    // 失败时弹窗必须留着：用户此刻的意图是"改这个字"，
    // 关掉等于把输入丢掉再让他重打一遍
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    const putCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'PUT',
    )
    expect(String(putCall?.[0])).toContain(`/tags/${MINE.id}`)
    // 描述没动过就原样带回来——PUT 是整份表示，省略等于清空
    expect(bodyOf(putCall?.[1] as RequestInit | undefined)).toEqual({
      name: '机器学习基础',
      description: '模型、训练与评测',
    })
  })

  it('清空描述时提交 null（而不是空串）', async () => {
    const fetchMock = login([])

    renderPage()
    await screen.findByText('机器学习')

    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    await screen.findByRole('dialog')

    fireEvent.change(await screen.findByLabelText('描述'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    const putCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === 'PUT',
    )
    // null 是"不要描述"的语义；空串会被后端 `TagDescription("")` 判成 40050（不能为空）
    expect(bodyOf(putCall?.[1] as RequestInit | undefined)).toEqual({
      name: '机器学习',
      description: null,
    })
  })
})
