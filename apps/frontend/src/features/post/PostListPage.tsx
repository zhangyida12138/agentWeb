import { formatDateTime } from '@agent-web/shared'
import { Link, useSearchParams } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { Pager } from '../../components/Pager'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'
import { PERMISSION } from '../access/permissions'

import { canCreatePost } from './permissions'
import { usePostsQuery } from './hooks'
import { PostStatusBadge } from './PostStatusBadge'

import type { ReactNode } from 'react'
import type { PostSummary } from './types'

/**
 * 文章列表（公开，无需登录）。
 *
 * 「未登录也能看」这个决定在这里落成两件具体的事：
 *   ① 页面**不**套 RequireAuth，路由直接挂在公开布局下；
 *   ② 它内部唯一的身份判断只有「要不要显示写文章按钮」，
 *      而那个判断的数据源（权限快照）在未登录时**根本不发请求**——
 *      否则游客打开这个页面会先吃一个 401，而 401 会清登录态，
 *      表现为「看别人的文章结果把自己登出了」。
 */

const PAGE_SIZE = 10

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/** 文章卡片。列表页与「我的文章」共用一套外观，差别只在右侧的动作区。 */
export function PostCard({
  post,
  actions,
  showStatus = false,
}: {
  post: PostSummary
  /** 卡片右下角的操作按钮（列表页不传，我的文章传编辑/发布/删除） */
  actions?: ReactNode
  /**
   * 是否显示状态徽章。
   *
   * 默认不显示：公开列表里每一篇都是已发布，一列「已发布」徽章只是噪声。
   * 只有「我的文章」需要它——那里草稿、已发布、已归档混在一起，
   * 不标状态的话根本分不清哪篇别人能看到。
   */
  showStatus?: boolean
}) {
  return (
    <article className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm transition-shadow hover:shadow-md">
      <div className="flex gap-4 p-5">
        {/* 封面只在有图时才渲染整个 img 容器，不留一块空白占位 */}
        {post.cover_url && (
          <Link to={`/posts/${post.slug}`} className="hidden shrink-0 sm:block">
            <img
              src={post.cover_url}
              alt=""
              className="h-20 w-28 rounded-lg bg-gray-100 object-cover"
            />
          </Link>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <h2 className="min-w-0 flex-1 text-base font-semibold text-gray-900">
              <Link to={`/posts/${post.slug}`} className="hover:text-brand">
                {post.title}
              </Link>
            </h2>
            {/* 列表页只列已发布，状态徽章由调用方决定要不要（见 showStatus） */}
            {showStatus && <PostStatusBadge status={post.status} />}
          </div>

          {post.summary && (
            // line-clamp-2：摘要超长时截断而不是把卡片撑成参差不齐的高度，
            // 列表的节奏比「多显示两行字」更重要
            <p className="mt-1 line-clamp-2 text-sm text-gray-500">{post.summary}</p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-400">
            <span>{formatDateTime(post.published_at, '未发布')}</span>
            <span>阅读 {post.view_count}</span>
            {post.tags.map((tag) => (
              <Link
                key={tag}
                to={`/posts?tag=${encodeURIComponent(tag)}`}
                className="rounded-full bg-gray-50 px-2 py-0.5 text-gray-600 hover:bg-gray-100"
              >
                #{tag}
              </Link>
            ))}
          </div>
        </div>
      </div>

      {actions && (
        <div className="flex justify-end gap-3 border-t border-gray-50 px-5 py-2">{actions}</div>
      )}
    </article>
  )
}

export function PostListPage() {
  /**
   * 分页与筛选放在 **URL** 里而不是组件 state。
   *
   * 理由是这一页的主要用法就是「点进一篇、看完按后退」：
   * 状态存在组件里的话，后退回来会重新从第一页开始，用户得再点一次「下一页」。
   * 放 URL 之后还顺带得到两个好处——列表页可以分享给别人的时候带上标签筛选，
   * 刷新也不会丢失位置。代价只是每次读 state 要 Number() 转一次。
   */
  const [searchParams, setSearchParams] = useSearchParams()
  const tag = searchParams.get('tag') || undefined
  // 手输 URL 可能带进 `?offset=abc`，Number 得到 NaN，兜底回 0：
  // 让服务端去收敛（它本来就会把负数按 0 处理）比在前端再写一遍校验更少分叉
  const offset = Number(searchParams.get('offset') ?? 0) || 0

  const { user } = useAuth()
  const accessQuery = useMyAccessQuery({ enabled: Boolean(user) })
  const canWrite = canCreatePost(accessQuery.data?.permission_codes)

  const postsQuery = usePostsQuery({ offset, limit: PAGE_SIZE, tag })

  /** 改 offset 时保留 tag；换 tag 时必须把 offset 清掉，否则会停在「新标签的第 3 页」 */
  const goToOffset = (nextOffset: number) => {
    const next = new URLSearchParams(searchParams)
    if (nextOffset > 0) next.set('offset', String(nextOffset))
    else next.delete('offset')
    setSearchParams(next, { replace: true })
  }

  const clearTag = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('tag')
    next.delete('offset')
    setSearchParams(next, { replace: true })
  }

  const posts = postsQuery.data?.items ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">文章</h1>
          <p className="mt-1 text-xs text-gray-500">
            {tag ? (
              <>
                标签筛选：<span className="text-gray-700">#{tag}</span>
                <button type="button" onClick={clearTag} className="ml-2 underline">
                  清除
                </button>
              </>
            ) : (
              '全部已发布的文章'
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {user && (
            <Link to="/my/posts" className="text-sm text-gray-600 hover:text-gray-900">
              我的文章
            </Link>
          )}
          {/* 未登录的人看得到这个按钮也没用（点了会去登录页），所以不给 */}
          {canWrite && (
            <Link
              to="/editor"
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              写文章
            </Link>
          )}
        </div>
      </div>

      {/*
        列表请求失败单独提示、保留页面框架：
        游客也可能遇到网络问题，此时给他一个「重试」比整页替换成错误更有用。
      */}
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
          {tag ? `没有标签为 #${tag} 的文章。` : '还没有已发布的文章。'}
        </div>
      )}

      {posts.map((post) => (
        <PostCard key={post.id} post={post} />
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

      {/*
        只在「确实还有权限点没匹配上」时给一句提示？不——这里什么都不说。
        游客不需要知道「写文章需要 post:create」，那是登录之后的事；
        把权限码甩给一个还没登录的人只会让他困惑。
        权限说明放在 MyPostsPage 与 RequirePermission 里，那里才是相关的场景。
      */}
      {user && !canWrite && accessQuery.data && (
        <p className="text-center text-xs text-gray-400">
          你没有「{PERMISSION.POST_CREATE}」权限，因此看不到写文章的入口。
        </p>
      )}
    </div>
  )
}
