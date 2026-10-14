import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { Pager } from '../../components/Pager'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'

import { DeletePostDialog } from './DeletePostDialog'
import { useMyPostsQuery, usePublishPostMutation, useUnpublishPostMutation } from './hooks'
import { canCreatePost, canDeletePost, canEditPost, canPublishPost } from './permissions'
import { PostCard } from './PostListPage'

import type { PostStatus, PostSummary } from './types'

/**
 * 「我的文章」：作者的工作台，含草稿与已归档。
 *
 * 这个页面**只要求登录**，不要求任何 `post:*` 权限，理由是后端同一条：
 *   内容的所有者就是调用者本人，归属已经是比权限码更强的约束。
 *   一个被收回作者角色的人仍然应该能翻到自己写过的草稿——
 *   内容没消失、所有者却访问不到，这在数据层面是不能接受的。
 *   所以路由守卫只用 RequireAuth，页面里也不再做一次权限判断。
 *
 * 排序按 `updated_at` 倒序（后端定）：作者在这个列表里找的是「我最近在弄哪一篇」。
 * 按发布时间排会让所有草稿挤成一团且顺序无意义——草稿根本没有发布时间。
 */

const PAGE_SIZE = 10

/**
 * 状态筛选项。
 *
 * 「全部」刻意不传 `status` 参数，而在后端用 `undefined` 表示不筛——
 * 前端这里不能写成 `status=all`：后端 `PostStatus.parse` 会把它当成非法值回 40035。
 * 两边对「不筛」的表达必须是同一个（缺省），中间不要造一个前端私有的枚举值。
 */
const STATUS_FILTERS = [
  { label: '全部', value: undefined },
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
  { label: '已归档', value: 'archived' },
] as const

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/** 把 URL 上的 status 参数收窄成已知状态，手输 `?status=xxx` 时按「全部」处理。 */
function parseStatus(value: string | null): PostStatus | undefined {
  if (value === 'draft' || value === 'published' || value === 'archived') return value
  return undefined
}

export function MyPostsPage() {
  const { user } = useAuth()
  const accessQuery = useMyAccessQuery()
  const codes = accessQuery.data?.permission_codes

  // 分页与筛选同样放 URL（理由见 PostListPage）：工作台最常发生的动作也是
  // 「编辑一篇 → 返回列表」，状态存在组件里的话返回后会跳回第一页
  const [searchParams, setSearchParams] = useSearchParams()
  const status = parseStatus(searchParams.get('status'))
  const offset = Number(searchParams.get('offset') ?? 0) || 0

  const postsQuery = useMyPostsQuery({ offset, limit: PAGE_SIZE, status })

  const publishMutation = usePublishPostMutation()
  const unpublishMutation = useUnpublishPostMutation()

  const [deleteTarget, setDeleteTarget] = useState<PostSummary | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const setStatusFilter = (next: PostStatus | undefined) => {
    const params = new URLSearchParams(searchParams)
    if (next) params.set('status', next)
    else params.delete('status')
    // 换筛选必须把 offset 清掉：否则会停在「新筛选条件的第 3 页」，
    // 而那多半是个空页，看起来像「筛选之后没有数据」
    params.delete('offset')
    setSearchParams(params, { replace: true })
  }

  const goToOffset = (nextOffset: number) => {
    const params = new URLSearchParams(searchParams)
    if (nextOffset > 0) params.set('offset', String(nextOffset))
    else params.delete('offset')
    setSearchParams(params, { replace: true })
  }

  const handleToggleStatus = async (post: PostSummary) => {
    setActionError(null)
    try {
      await (post.status === 'published'
        ? unpublishMutation.mutateAsync(post.id)
        : publishMutation.mutateAsync(post.id))
    } catch (error) {
      setActionError(errorMessage(error, '操作失败'))
    }
  }

  const posts = postsQuery.data?.items ?? []
  const canWrite = canCreatePost(codes)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">我的文章</h1>
          <p className="mt-1 text-xs text-gray-500">
            草稿只有你自己能看到；发布之后才会出现在公开列表里。
          </p>
        </div>
        {canWrite && (
          <Link
            to="/editor"
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            写文章
          </Link>
        )}
      </div>

      {/* 状态筛选做成一排按钮而不是下拉：可选项只有四个，全部平铺比藏进下拉少一次点击 */}
      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((filter) => {
          const active = filter.value === status
          return (
            <button
              key={filter.label}
              type="button"
              onClick={() => setStatusFilter(filter.value)}
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

      {actionError && <Alert tone="error">{actionError}</Alert>}

      {postsQuery.error && (
        <Alert tone="error">
          {errorMessage(postsQuery.error, '无法加载文章列表')}
          <button
            type="button"
            onClick={() => void postsQuery.refetch()}
            className="ml-2 underline"
          >
            重试
          </button>
        </Alert>
      )}

      {postsQuery.isPending && <p className="text-sm text-gray-500">加载中…</p>}

      {!postsQuery.isPending && posts.length === 0 && (
        <div className="rounded-2xl border border-gray-100 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
          {status === 'draft' && '没有草稿。'}
          {status === 'published' && '还没有发布过文章。'}
          {status === 'archived' && '没有已下架的文章。'}
          {!status && (
            <>
              还没有写过文章。
              {canWrite && (
                <Link to="/editor" className="ml-2 text-brand hover:opacity-70">
                  写第一篇
                </Link>
              )}
            </>
          )}
        </div>
      )}

      {posts.map((post) => (
        <PostCard
          key={post.id}
          post={post}
          showStatus
          actions={
            <>
              {canEditPost(codes, post, user?.id) && (
                <Link
                  to={`/editor/${encodeURIComponent(post.slug)}`}
                  className="text-sm text-brand transition-opacity hover:opacity-70"
                >
                  编辑
                </Link>
              )}

              {canPublishPost(codes, post, user?.id) && (
                <button
                  type="button"
                  // 只禁用**这一行**的按钮：用 mutation.variables 比对，
                  // 否则点某一行时整个列表的按钮都会一起变灰
                  disabled={
                    (publishMutation.isPending && publishMutation.variables === post.id) ||
                    (unpublishMutation.isPending && unpublishMutation.variables === post.id)
                  }
                  onClick={() => void handleToggleStatus(post)}
                  className="text-sm text-brand transition-opacity hover:opacity-70 disabled:opacity-40"
                >
                  {post.status === 'published' ? '下架' : '发布'}
                </button>
              )}

              {canDeletePost(codes, post, user?.id) && (
                <button
                  type="button"
                  onClick={() => setDeleteTarget(post)}
                  className="text-sm text-red-600 transition-opacity hover:opacity-70"
                >
                  删除
                </button>
              )}

              {/* 三个动作一个都没有时给个占位，避免操作区塌成空白让卡片高度不一致 */}
              {!canEditPost(codes, post, user?.id) &&
                !canPublishPost(codes, post, user?.id) &&
                !canDeletePost(codes, post, user?.id) && (
                  <span className="text-xs text-gray-400">仅可查看</span>
                )}
            </>
          }
        />
      ))}

      {postsQuery.data && (
        <Pager
          offset={postsQuery.data.offset}
          limit={postsQuery.data.limit}
          total={postsQuery.data.total}
          itemCount={posts.length}
          isFetching={postsQuery.isFetching}
          onOffsetChange={goToOffset}
        />
      )}

      {deleteTarget && (
        // key 绑定文章 id：换一篇时强制重建弹窗内部状态，
        // 否则上一篇的失败提示会带着飘到下一篇上（看着像「还没删就报错了」）
        <DeletePostDialog
          key={deleteTarget.id}
          post={deleteTarget}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}
