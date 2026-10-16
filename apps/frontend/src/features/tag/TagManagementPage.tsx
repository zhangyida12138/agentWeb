import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { Pager } from '../../components/Pager'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { PERMISSION } from '../access/permissions'
import { useMyAccessQuery } from '../access/hooks'

import { DeleteTagDialog } from './DeleteTagDialog'
import { CreateTagDialog, EditTagDialog } from './TagFormDialog'
import { TagStatusTabs } from './TagStatusTabs'
import { TagTable } from './TagTable'
import { useChangeTagStatusMutation, useDeleteTagMutation, useTagsQuery } from './hooks'
import { canManageTags } from './permissions'

import type { Tag, TagStatusValue, TagTypeValue } from './types'

/**
 * 「标签管理」——**管理员维度**的标签管理。
 *
 * ── 与「我的标签」的关系：同一个资源、两套动作集合 ──
 * 用户提的需求是"管理员和作者都能管理，只是维度不同"。落到代码上，
 * 这个"维度"就是两个具体的差别，而不是一句抽象的话：
 *
 *   ① **范围**：作者看 `author_id = 我`，管理员看全部。
 *   译者注：这里的"全部"是真的全部——包括 `system` 类型、
 *   包括 `author_id` 为 null 的无主标签。前者是平台预置的入口，
 *   后者是创建者已注销的存量数据，它们**只有管理员能看见、能处理**。
 *
 *   ② **动作**：作者只能改名字与描述，管理员还能新建 / 下架 / 恢复 / 删除。
 *   这三个额外动作全部落在 `tag:manage` 上，而路由守卫也挂的是它——
 *   也就是说"能到达这个页面"和"能做这些动作"是同一个条件，
 *   不存在"进来了但按钮点不动"的中间态。
 *
 * ── 为什么是两个页面而不是一个页面上加条件 ──
 * 一个页面（比如 `/tags` + 按权限显示不同按钮）在实现上完全可行，
 * 但那会把两个不同的**心流**糅在一起：
 *   作者来这里是「把我的标签整理一下」，管理员来这里是「术语表里有哪些脏数据」。
 * 前者需要"我的"这个上下文（越权看到全站标签对他只是噪音），
 * 后者需要类型/创建者这些治理信息（对作者是看不懂的列）。
 * 合成一个页面，两边的默认筛选、默认排序列、空态文案全都要靠 `if` 分叉——
 * 那些 `if` 就是"其实是两个页面"的证据。拆开之后它们各自只需要一个 `variant`。
 */

const PAGE_SIZE = 20

/** 类型筛选。与状态不同，`type` **可以**用"不传"表达"全部"（后端默认不筛）。 */
const TYPE_FILTERS = [
  { label: '全部类型', value: undefined },
  { label: '官方', value: 'system' },
  { label: '用户', value: 'user' },
] as const

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function parseStatus(value: string | null): TagStatusValue {
  if (value === 'abnormal' || value === 'deleted') return value
  return 'normal'
}

/** 手输 `?type=xxx` 时按「全部类型」处理，与 MyPostsPage 对非法 status 的处理一致。 */
function parseType(value: string | null): TagTypeValue | undefined {
  if (value === 'system' || value === 'user') return value
  return undefined
}

export function TagManagementPage() {
  const { user } = useAuth()
  const accessQuery = useMyAccessQuery()
  const codes = accessQuery.data?.permission_codes
  const managesTags = canManageTags(codes)

  const [searchParams, setSearchParams] = useSearchParams()
  const status = parseStatus(searchParams.get('status'))
  const type = parseType(searchParams.get('type'))
  const keyword = searchParams.get('keyword') ?? ''
  const offset = Number(searchParams.get('offset') ?? 0) || 0

  const [keywordDraft, setKeywordDraft] = useState(keyword)

  /**
   * `enabled: managesTags` 是这一页的关键。
   *
   * 两个理由，缺一个都不行：
   *   ① 权限还没加载完（`codes` 为 undefined）时，`managesTags` 是 false——
   *      请求不发，页面等权限。反过来的话，一个没有权限的人打开这个地址
   *      会先看到一次 403 的错误提示，然后才被路由守卫弹走，中间的闪烁是纯噪音。
   *   ② 路由守卫本身也要等权限加载完才有结论。`enabled` 让页面和守卫
   *      用同一个条件做同一个决定，不会出现"守卫放行、页面不发请求"的空窗。
   */
  const tagsQuery = useTagsQuery(
    { offset, limit: PAGE_SIZE, status, type, keyword },
    { enabled: managesTags },
  )

  const statusMutation = useChangeTagStatusMutation()
  const deleteMutation = useDeleteTagMutation()

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Tag | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Tag | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  /**
   * 恢复动作的说明文案。
   *
   * 单独一个 state 而不是复用 `actionError`：那条提示的语义是"成功但结果不直观"，
   * 而 `actionError` 是失败。共用一个变量的话，成功和失败会互相覆盖——
   * 用户在同一个位置看到两种颜色交替的消息，分不清哪条是现在的状态。
   */
  const [statusNotice, setStatusNotice] = useState<string | null>(null)

  const setParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(searchParams)
    if (value) params.set(key, value)
    else params.delete(key)
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
    setStatusNotice(null)
    const next: TagStatusValue = tag.status === 'normal' ? 'abnormal' : 'normal'
    try {
      const updated = await statusMutation.mutateAsync({ tagId: tag.id, status: next })
      // 恢复一个已删除的标签时**必须**提示：它默认落在「正常」tab 里，
      // 而管理员此刻多半正在「已删除」tab 上——列表刷新后那一行直接消失了。
      // 没有这句反馈，看起来就像"点了一下把它点没了"。
      if (tag.status === 'deleted') {
        setStatusNotice(`「${updated.name}」已恢复为「正常」，现在只出现在「正常」这一档里。`)
      }
    } catch (error) {
      setActionError(errorMessage(error, '操作失败'))
    }
  }

  /**
   * 正在处理的那一行。
   * 两个 mutation 共用一个"哪一行在忙"的位置：它们不会同时发生
   * （都是用户一次点击触发的），所以按"谁在 pending 就是谁"取即可。
   */
  const pendingTagId = statusMutation.isPending
    ? (statusMutation.variables?.tagId ?? null)
    : deleteMutation.isPending
      ? (deleteMutation.variables ?? null)
      : null

  const tags = tagsQuery.data?.items ?? []

  // 权限还没结论前不渲染页面的任何一部分：先"加载中"，再"缺权限"，
  // 最后才是内容。这个顺序保证用户不会看到一个随后会被自己权限推翻的界面。
  if (accessQuery.isPending) {
    return <p className="text-sm text-gray-500">加载中…</p>
  }

  if (accessQuery.error) {
    return <Alert tone="error">{errorMessage(accessQuery.error, '无法加载权限信息')}</Alert>
  }

  if (!managesTags) {
    return (
      <Alert tone="error">
        你没有「管理标签」（{PERMISSION.TAG_MANAGE}）的权限，无法访问标签管理。
        这里可以新建、下架、删除**全站共用**的标签，所以只有管理员能进来。
        如果你只是想改自己创建的标签，请到
        <Link to="/my/tags" className="mx-1 underline">
          我的标签
        </Link>
        。
      </Alert>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">标签管理</h1>
          <p className="mt-1 text-xs text-gray-500">
            标签是全局共用的：所有文章、所有作者看到的都是这一份。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          新建标签
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <TagStatusTabs value={status} onChange={(next) => setParam('status', next)} />
          <span className="text-gray-200">|</span>
          <div className="flex flex-wrap gap-2">
            {TYPE_FILTERS.map((filter) => {
              const active = filter.value === type
              return (
                <button
                  key={filter.label}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setParam('type', filter.value ?? null)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    active
                      ? 'border-brand bg-purple-50 text-brand'
                      : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {filter.label}
                </button>
              )
            })}
          </div>
        </div>

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
      {statusNotice && <Alert tone="info">{statusNotice}</Alert>}

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
          {keyword
            ? `没有名字包含「${keyword}」的标签。`
            : status === 'normal'
              ? '没有符合条件的标签。'
              : status === 'abnormal'
                ? '没有被下架的标签。没有被下架是好事。'
                : '没有被删除的标签。'}
        </div>
      )}

      {tags.length > 0 && (
        <TagTable
          tags={tags}
          codes={codes}
          currentUserId={user?.id}
          variant="manage"
          onEdit={setEditTarget}
          onToggleStatus={handleToggleStatus}
          onDelete={setDeleteTarget}
          pendingTagId={pendingTagId}
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

      {createOpen && (
        <CreateTagDialog
          onClose={() => setCreateOpen(false)}
          // 新建完停在"正常"这一档：新标签一定是 normal，
          // 若用户此刻正在"已删除"tab 上，不切回来的话他刚建的东西根本看不见
          onSaved={() => setParam('status', 'normal')}
        />
      )}

      {editTarget && <EditTagDialog tag={editTarget} onClose={() => setEditTarget(null)} />}

      {deleteTarget && <DeleteTagDialog tag={deleteTarget} onClose={() => setDeleteTarget(null)} />}
    </div>
  )
}
