import { formatDateTime } from '@agent-web/shared'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'
import { CommentTree } from '../comment/CommentTree'
import { PostInteractionBar } from '../like/PostInteractionBar'

import { DeletePostDialog } from './DeletePostDialog'
import { usePostQuery, usePublishPostMutation, useUnpublishPostMutation } from './hooks'
import { MarkdownContent } from './MarkdownContent'
import { canDeletePost, canEditPost, canPublishPost } from './permissions'
import { PostStatusBadge } from './PostStatusBadge'

/**
 * 文章详情（公开，无需登录）。
 *
 * 这一页同时是「游客的阅读页」和「作者的预览页」——同一条 URL、同一个请求，
 * 区别只在 token：
 *   后端 `GetPostBySlugUseCase` 会拿可选身份去判可见性，作者能看到自己的草稿，
 *   游客看别人的草稿拿到的是 **404 而不是 403**（别人未发布的内容，
 *   其存在性本身就是私有信息）。
 *   所以 404 的文案不点破「这可能是一篇别人的草稿」——对访问者来说
 *   「不存在」和「不给你看」应该是同一个观察结果，说破了反而泄露了信息。
 *
 * 阅读量：后端只在「访问者不是作者本人」时 +1，所以作者自己刷新这一页
 * 看到的数字不会变，这是有意的（否则作者刷几次就把数据刷糊了）。
 */

const NOT_FOUND_CODE = 40430

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function PostDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()

  const postQuery = usePostQuery(slug)
  const accessQuery = useMyAccessQuery({ enabled: Boolean(user) })
  const codes = accessQuery.data?.permission_codes

  const publishMutation = usePublishPostMutation()
  const unpublishMutation = useUnpublishPostMutation()

  const [confirmingDelete, setConfirmingDelete] = useState(false)
  /** 操作失败（发布/删除）就地提示，不整页替换——内容本身是好的，不该被一个失败按钮带走 */
  const [actionError, setActionError] = useState<string | null>(null)

  const post = postQuery.data

  if (postQuery.isPending) {
    return <p className="text-sm text-gray-500">加载中…</p>
  }

  if (postQuery.error || !post) {
    const error = postQuery.error
    const isNotFound = error instanceof ApiError && error.code === NOT_FOUND_CODE

    return (
      <div className="flex flex-col gap-4">
        <Alert tone="error">
          {isNotFound
            ? '找不到这篇文章。它可能已被删除，或者还没有发布。'
            : errorMessage(error, '无法加载这篇文章')}
        </Alert>
        <Link to="/posts" className="text-sm text-brand hover:opacity-70">
          ← 返回文章列表
        </Link>
      </div>
    )
  }

  // 三把尺子分开算，和后端的三处判断一一对应，理由见 permissions.ts
  const editable = canEditPost(codes, post, user?.id)
  const publishable = canPublishPost(codes, post, user?.id)
  const deletable = canDeletePost(codes, post, user?.id)

  const isPublished = post.status === 'published'

  const handleToggleStatus = async () => {
    setActionError(null)
    try {
      // 已发布 → 下架；其余（草稿 / 已归档）→ 发布。两者是同一个「可见性开关」的两面
      await (isPublished ? unpublishMutation : publishMutation).mutateAsync(post.id)
    } catch (error) {
      setActionError(errorMessage(error, '操作失败'))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link to="/posts" className="text-sm text-gray-500 hover:text-gray-900">
        ← 返回文章列表
      </Link>

      <header className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <h1 className="min-w-0 flex-1 text-2xl font-semibold text-gray-900">{post.title}</h1>
          <PostStatusBadge status={post.status} />
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400">
          <span>{post.published_at ? formatDateTime(post.published_at) : '未发布'}</span>
          <span>阅读 {post.view_count}</span>
          <span>更新于 {formatDateTime(post.updated_at)}</span>
          {/* slug 是永久链接，作者需要看到它才能把地址发给别人 */}
          <span className="font-mono">/{post.slug}</span>
        </div>

        {post.tags.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {post.tags.map((tag) => (
              <Link
                key={tag}
                to={`/posts?tag=${encodeURIComponent(tag)}`}
                className="rounded-full bg-gray-50 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-100"
              >
                #{tag}
              </Link>
            ))}
          </div>
        )}
      </header>

      {actionError && <Alert tone="error">{actionError}</Alert>}

      {post.cover_url && (
        <img
          src={post.cover_url}
          alt=""
          className="max-h-80 w-full rounded-2xl bg-gray-100 object-cover"
        />
      )}

      {/* 整页唯一渲染 Markdown 的地方，安全说明见 MarkdownContent 的文档 */}
      <MarkdownContent content={post.content} />

      {/*
        归档状态给作者一句解释：链接仍然可达但不在公开列表里，
        这件事光看状态徽章不容易意识到（这也是「下架 ≠ 删除」的关键差别）。
      */}
      {post.status === 'archived' && (
        <p className="text-xs text-gray-400">
          这篇文章已下架，不会出现在公开列表里，但永久链接仍然可以打开。
        </p>
      )}

      {/**
       * 互动区。`interactionsOpen` 传的是「已发布」：后端把起草与已下架
       * 都当作「不接受新的互动」（40940），两者在这里的表现也一样——
       * 已有的赞和评论照常显示，只是不能再新增。
       * 用 `=== 'published'` 而不是 `!== 'archived'`：将来若多出别的状态，
       * 默认落到「不能互动」比默认落到「能互动」安全。
       */}
      <PostInteractionBar postId={post.id} interactionsOpen={isPublished} />

      {/**
       * 评论区放在正文与作者操作栏之间：评论是给读者看的，
       * 而最下面那条是作者的编辑/发布/删除按钮——把读者内容夹在读者信息
       * 和作者工具之间会让作者每次滚到底部都要穿过一整个评论区。
       */}
      <CommentTree postId={post.id} interactionsOpen={isPublished} />

      {/* 一个操作按钮都没有时整条栅都别渲染，避免留下一条空白的分隔线 */}
      {(editable || publishable || deletable) && (
        <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-gray-100 pt-4">
          {editable && (
            <Link
              to={`/editor/${encodeURIComponent(post.slug)}`}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              编辑
            </Link>
          )}

          {publishable && (
            <button
              type="button"
              disabled={publishMutation.isPending || unpublishMutation.isPending}
              onClick={() => void handleToggleStatus()}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
            >
              {isPublished ? '下架' : '发布'}
            </button>
          )}

          {deletable && (
            <button
              type="button"
              onClick={() => setConfirmingDelete(true)}
              className="rounded-lg border border-red-200 px-4 py-2 text-sm text-red-600 hover:bg-red-50"
            >
              删除
            </button>
          )}
        </footer>
      )}

      {confirmingDelete && (
        <DeletePostDialog
          post={post}
          onClose={() => setConfirmingDelete(false)}
          // 删完不能留在详情页：那个 slug 已经 404，而页面手上还拿着缓存里的内容，
          // 看着像「删除没生效」。用 replace：走后不该还能靠「后退」回到已删除的文章
          onDeleted={() => navigate('/my/posts', { replace: true })}
        />
      )}
    </div>
  )
}
