import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { Pager } from '../../components/Pager'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'

import { EditTagDialog } from './TagFormDialog'
import { TagStatusTabs } from './TagStatusTabs'
import { TagTable } from './TagTable'
import { useChangeTagStatusMutation, useTagsQuery } from './hooks'
import { canManageTags } from './permissions'

import type { Tag, TagStatusValue } from './types'

/**
 * 「我的标签」——**作者维度**的标签管理。
 *
 * ── 这个页面为什么只要求登录，不要求任何 `tag:*` 权限 ──
 * 与 `/my/posts` 同一条理由，而且更硬：这里的约束是**归属**，不是权限。
 * 传出去的查询里带着 `author_id = 我`，所以「能看到什么」和「能改什么」
 * 都由这一条决定——权限再收一遍也只是把"自己的东西"变成"自己有权看的自己的东西"，
 * 而后者不存在。后端对此的对应实现是 `Tag.ensure_manageable_by` 里
 * 「user · 我的 → 任何人」那一行。
 *
 * ── 作者在这个页面上能做什么、不能做什么 ──
 *   能：改自己标签的**名字与描述**（`PUT /tags/{id}`，唯一的无守卫写接口）。
 *   不能：新建（`POST /tags` 要 `tag:manage`）、下架、删除（都要 `tag:manage`）。
 *
 * 那"作者的标签从哪来"？——**写文章时第一次用到那个名字**。
 * 那条链路由 `post:create` 保护，会顺带建出标签并把 `author_id` 记成作者。
 * 这是一种有意的顺序倒置：「先写下来、再整理术语」比「先申请术语、才有资格写」
 * 短得多，也不会让一个想写"Rust 所有权"的人先卡在术语表审批上。
 * 所以这个页面**没有**「新建标签」按钮，取而代之的是页面顶部把这件事说清楚，
 * 否则用户只会觉得功能缺了一块。
 *
 * ── 为什么作者也能看到「已下架 / 已删除」 ──
 * 接口天然支持（`author_id` 已经把自己收窄了），而这三个 tab 恰好回答
 * 「我写的那个标签怎么不见了」——这个问题的答案不该只有管理员看得到。
 * 但作者在那些行上没有「恢复」按钮（那是 `tag:manage` 的动作），
 * 于是他看到的是"它还在、只是被下架了"，而不是"它凭空消失了"。
 */

const PAGE_SIZE = 20

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/**
 * 把 URL 上的 `status` 收窄成已知取值。
 *
 * 与 MyPostsPage 不同，这里**没有「全部」**（后端表达不了），所以缺省值是
 * `normal` 而不是 `undefined`。缺省值写在前端而不是交给后端默认，
 * 是为了让"URL 上没写"和"界面显示什么"永远一致：
 * 依赖后端默认的话，后端哪天把默认改成 `abnormal`，界面上的 tab 会静静地
 * 高亮错一项——一个不会报错、只是显示错误的 bug。
 */
function parseStatus(value: string | null): TagStatusValue {
  if (value === 'abnormal' || value === 'deleted') return value
  return 'normal'
}

export function MyTagsPage() {
  const { user } = useAuth()
  const accessQuery = useMyAccessQuery()
  const codes = accessQuery.data?.permission_codes

  // 筛选与分页放 URL（理由同 PostListPage）：最常见的动作是
  // 「改完一个 → 返回列表」，状态存在组件里的话返回后会跳回第一页、丢掉筛选。
  const [searchParams, setSearchParams] = useSearchParams()
  const status = parseStatus(searchParams.get('status'))
  const keyword = searchParams.get('keyword') ?? ''
  const offset = Number(searchParams.get('offset') ?? 0) || 0

  // 搜索框的草稿态：输入过程不动 URL（否则每敲一个字都写一次 history +
  // 发一次请求）。它只在"提交搜索"或"清除"时同步到 URL。
  const [keywordDraft, setKeywordDraft] = useState(keyword)

  /**
   * `authorId: user?.id` 是这个页面的**全部约束**，所以 `enabled` 不能省。
   *
   * 若 `user` 还没就绪（token 有、user 为 null 的瞬间）就发请求，
   * `authorId` 是 undefined → 后端把 `author_id` 当"不筛" → **返回全站标签**。
   * 一份看起来完全正常的列表，内容却是所有人的——这类失败不会报错，
   * 只会安静地显示错误的东西。宁可不发这个请求。
   */
  const tagsQuery = useTagsQuery(
    { offset, limit: PAGE_SIZE, status, keyword, authorId: user?.id },
    { enabled: Boolean(user?.id) },
  )

  const statusMutation = useChangeTagStatusMutation()
  const [editTarget, setEditTarget] = useState<Tag | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const setParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(searchParams)
    if (value) params.set(key, value)
    else params.delete(key)
    // 换筛选必须清 offset：否则会停在「新筛选条件的第 3 页」，
    // 那多半是空页，看起来像"筛完之后什么都没有"
    params.delete('offset')
    setSearchParams(params, { replace: true })
  }

  const goToOffset = (nextOffset: number) => {
    const params = new URLSearchParams(searchParams)
    if (nextOffset > 0) params.set('offset', String(nextOffset))
    else params.delete('offset')
    setSearchParams(params, { replace: true })
  }

  const handleToggleStatus = async (tag: Tag) => {
    setActionError(null)
    // 与表格里的文案同一条规则：normal → 下架，其余 → 恢复。
    // 这里刻意重复这一个判断而不从表格里导出：表格的 `statusAction` 决定的是
    // "按钮上写什么字"，这里决定的是"点了之后发什么请求"。共用一个函数会让
    // 改文案的人意外改掉行为——它们的**形状**相同是巧合，不是同一条规则。
    const next: TagStatusValue = tag.status === 'normal' ? 'abnormal' : 'normal'
    try {
      await statusMutation.mutateAsync({ tagId: tag.id, status: next })
    } catch (error) {
      setActionError(errorMessage(error, '操作失败'))
    }
  }

  const tags = tagsQuery.data?.items ?? []
  const managesTags = canManageTags(codes)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">我的标签</h1>
          <p className="mt-1 text-xs text-gray-500">
            这里是你创建的标签。你可以改它们名字和描述；用来写作的是
            <Link to="/my/posts" className="mx-1 text-brand hover:opacity-70">
              我的文章
            </Link>
            。
          </p>
        </div>
        {/* 管理入口只对拿 tag:manage 的人显示：对作者来说，一个点不开的
            「标签管理」比没有这个入口更让人困惑（他会以为是自己权限配错了） */}
        {managesTags && (
          <Link
            to="/admin/tags"
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            标签管理
          </Link>
        )}
      </div>

      {/*
        「我的标签从哪来」是页面上最容易被问的问题，所以直接写在页面里而不是
        塞进一个折叠的帮助里。**这不是权限缺失，是流程设计**——把原因讲清楚，
        用户就不会去翻「为什么没有新建按钮」。
      */}
      <p className="rounded-2xl border border-gray-100 bg-white p-4 text-xs text-gray-500 shadow-sm">
        标签是在写文章时第一次用到某个名字时自动创建的，所以这里没有「新建」按钮。
        新建和删除标签由管理员统一处理（术语表是全局共用的，一个作者删掉它
        会同时影响别人已发布的文章）。
      </p>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <TagStatusTabs value={status} onChange={(next) => setParam('status', next)} />

        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            setParam('keyword', keywordDraft.trim() || null)
          }}
        >
          <input
            type="search"
            value={keywordDraft}
            onChange={(event) => setKeywordDraft(event.target.value)}
            placeholder="按名称搜索"
            aria-label="按名称搜索标签"
            className="w-40 rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-purple-100"
          />
          <button
            type="submit"
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            搜索
          </button>
          {/* 清除只在确实有筛选时出现：常驻一个点了没反应的按钮会让人怀疑它坏了 */}
          {keyword && (
            <button
              type="button"
              onClick={() => {
                setKeywordDraft('')
                setParam('keyword', null)
              }}
              className="text-sm text-gray-500 underline hover:text-gray-700"
            >
              清除
            </button>
          )}
        </form>
      </div>

      {actionError && <Alert tone="error">{actionError}</Alert>}

      {tagsQuery.error && (
        <Alert tone="error">
          {errorMessage(tagsQuery.error, '无法加载标签列表')}
          <button type="button" onClick={() => void tagsQuery.refetch()} className="ml-2 underline">
            重试
          </button>
        </Alert>
      )}

      {tagsQuery.isPending && <p className="text-sm text-gray-500">加载中…</p>}

      {!tagsQuery.isPending && tags.length === 0 && (
        <div className="rounded-2xl border border-gray-100 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
          {keyword && `没有名字包含「${keyword}」的标签。`}
          {!keyword &&
            status === 'normal' &&
            '你还没有创建过标签。写文章时用到一个新标签名，它就会出现在这里。'}
          {!keyword && status === 'abnormal' && '没有被下架的标签。'}
          {!keyword && status === 'deleted' && '没有被删除的标签。'}
        </div>
      )}

      {tags.length > 0 && (
        <TagTable
          tags={tags}
          codes={codes}
          currentUserId={user?.id}
          variant="mine"
          onEdit={setEditTarget}
          // 作者维度没有治理动作：这里传的是空实现，表格也不会渲染出按钮
          // （`variant="mine"` 下 showStatusActions 恒为 false）。
          // 传 `() => {}` 而不是让 prop 可选，是为了在类型上保持"表格总是有这三个回调"，
          // 免得将来有人以为"没传 = 这个功能没做"而去别处实现一遍。
          onToggleStatus={handleToggleStatus}
          onDelete={() => {}}
          pendingTagId={statusMutation.isPending ? (statusMutation.variables?.tagId ?? null) : null}
        />
      )}

      {tagsQuery.data && (
        <Pager
          offset={tagsQuery.data.offset}
          limit={tagsQuery.data.limit ?? PAGE_SIZE}
          total={tagsQuery.data.total}
          itemCount={tags.length}
          isFetching={tagsQuery.isFetching}
          onOffsetChange={goToOffset}
          unit="个"
        />
      )}

      {editTarget && <EditTagDialog tag={editTarget} onClose={() => setEditTarget(null)} />}
    </div>
  )
}
