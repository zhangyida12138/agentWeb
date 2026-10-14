import { formatDateTime } from '@agent-web/shared'
import { useState } from 'react'

import { Alert } from '../../components/Alert'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'
import { LikeButton } from '../like/LikeButton'

import { CommentForm } from './CommentForm'
import { useDeleteCommentMutation, useToggleCommentLikeMutation } from './hooks'
import { canCreateComment, canDeleteComment } from './permissions'

import type { CommentNode } from './types'

/**
 * 一条评论（含它下面的全部回复）。
 *
 * 递归渲染，**层数不限**：树能多深由用户之间的对话决定。
 * 但视觉上只给**一层**缩进——第一层回复的容器带左边框和内缩，更深的容器不再叠加。
 * 因为子节点的容器本来就嵌在父节点的容器里面，只要第二层起不加内缩，
 * 它们自然就停在同一个位置上，于是「回复的回复」看起来是平铺的一条线，
 * 而不是一路缩到屏幕外面去。
 *
 *   ⚠️ 所以 `depth` 只用来判断「要不要加那一层缩进」，**不是乘数**。
 *      写成 `paddingLeft: depth * 16` 是这类组件最常见的错法，
 *      长对话一来就会把正文挤成一条竖线。
 *
 * 用户点回复时把 `parent_id` 设成**那一条回复的 id**——包括回复一条回复：
 *   后端原样记录，不做「归一到根」那种折算，所以三层、四层都是合法的。
 *   缩进几层是这个文件的选择，与数据的形状无关。
 *
 * 作者名由**后端**给出（`author_display_name` / `parent_author_display_name`）。
 *   前端不要为了显示名字去按 id 拉 `/users/{id}`：那是把 N+1 从数据库
 *   搬到了浏览器（一页几十个请求），而且在匿名可读的评论区里，
 *   那些请求会因为需要鉴权而变成 401/403。
 *   名字是展示字段，「谁能看到谁的名字」由后端在一次查询里一起决定。
 *
 * 为什么这里要自己调 `useMyAccessQuery`：同 `PostInteractionBar`。
 * 同一个 queryKey，React Query 去重，不会多发请求；
 * 好处是每个评论项自带「我能不能删它」需要的全部信息。
 */

interface CommentItemProps {
  comment: CommentNode
  postId: string
  /** 文章是否接受新的互动（已发布）。已下架的文章只能看，不能再评/再赞。 */
  interactionsOpen: boolean
  /**
   * 当前层级（0 = 根评论，1 = 第一层回复，2 = 回复的回复……）。
   *
   * 只用来判断「要不要加那一层缩进」，见下面的 `wrapperClass`。**不是**缩进倍数。
   */
  depth?: number
}

export function CommentItem({ comment, postId, interactionsOpen, depth = 0 }: CommentItemProps) {
  const { user } = useAuth()
  const accessQuery = useMyAccessQuery({ enabled: Boolean(user) })
  const codes = accessQuery.data?.permission_codes

  const [replying, setReplying] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const likeMutation = useToggleCommentLikeMutation()
  const deleteMutation = useDeleteCommentMutation(postId)

  const canReply = canCreateComment(codes) && interactionsOpen
  const canDelete = canDeleteComment(codes, comment, user?.id)

  const handleToggleLike = async () => {
    setActionError(null)
    try {
      await likeMutation.mutateAsync({ postId, commentId: comment.id })
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : '操作失败')
    }
  }

  const handleDelete = async () => {
    setActionError(null)
    try {
      await deleteMutation.mutateAsync(comment.id)
    } catch (error) {
      // 40440：这条评论在别处已经被撤回了。列表要刷新才能反映现实，
      // 所以这里提示之后顺手让缓存失效（mutation 的 onSuccess 不会跑，
      // 失败路径只能自己来）。
      setActionError(error instanceof ApiError ? error.message : '删除失败')
    }
  }

  /*
        缩进只加一层：depth === 1 的容器带左边框和内缩，更深的容器只留上边距。
        子节点的容器是嵌在父节点容器里的，所以「不加内缩」= 停在父节点的缩进位置上，
        第一层回复、回复的回复、再往下，视觉上都在同一条竖线上。
      */
  const wrapperClass =
    depth === 0 ? '' : depth === 1 ? 'mt-3 border-l-2 border-gray-100 pl-4' : 'mt-3'

  return (
    <article className={wrapperClass}>
      <div className="rounded-lg border border-gray-200 p-4">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
          <span title={comment.author_id}>用户 {comment.author_display_name}</span>
          {/*
                      只有真的回复了别人时才渲染「回复 xxx」。
                      parent_id 与 parent_author_display_name 同生共死，本可以只判一个；
                      判两个是为了让 TS 把类型收窄，省掉非空断言。
                      被回复的那条即使已被撤回，名字照给——这里刻意不做特殊处理：
                      撤回的是内容，不是「谁回复过谁」。
                    */}
          {comment.parent_id !== null && comment.parent_author_display_name !== null && (
            <span className="text-gray-400" title={comment.parent_id}>
              回复 {comment.parent_author_display_name}
            </span>
          )}
          <time dateTime={comment.created_at}>{formatDateTime(comment.created_at)}</time>
          {comment.is_deleted && (
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-500">已撤回</span>
          )}
        </header>

        <div className="mt-2 text-sm text-gray-800">
          {comment.is_deleted ? (
            /*
                                      墓碑：撤回后节点仍然留在树上。
                                      不能把整块 `return null` 掉——它有回复的话，
                                      那些回复会跟着消失，看起来像「别人的评论被删了」。
                                      用 `whitespace-pre-line` 保留用户敲的换行（评论没有 Markdown 渲染，
                                      纯文本展示，所以换行只能靠 CSS 保留）。
                                    */
            <p className="italic text-gray-400">该评论已被作者撤回</p>
          ) : (
            <p className="whitespace-pre-line break-words">{comment.content}</p>
          )}
        </div>

        {actionError && (
          <div className="mt-2">
            <Alert tone="error">{actionError}</Alert>
          </div>
        )}

        <footer className="mt-3 flex flex-wrap items-center gap-3">
          <LikeButton
            liked={comment.liked_by_me}
            likeCount={comment.like_count}
            isPending={likeMutation.isPending}
            // 游客仍看得到赞数，只是点不了；已撤回的评论也不该被点赞
            disabled={!user || !interactionsOpen || comment.is_deleted}
            disabledReason={!user ? '登录后可点赞' : !interactionsOpen ? '文章已下架' : undefined}
            onToggle={() => void handleToggleLike()}
            className="!px-2 !py-1 !text-xs"
          />

          {canReply && (
            <button
              type="button"
              onClick={() => setReplying((previous) => !previous)}
              className="text-xs text-gray-500 transition-colors hover:text-brand"
            >
              {replying ? '收起' : '回复'}
            </button>
          )}

          {canDelete && (
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={deleteMutation.isPending}
              className="text-xs text-gray-500 transition-colors hover:text-red-600 disabled:opacity-50"
            >
              {deleteMutation.isPending ? '撤回中…' : '撤回'}
            </button>
          )}
        </footer>

        {replying && (
          <div className="mt-3">
            <CommentForm
              postId={postId}
              // 传的是这条评论自己的 id（它可能本身就是一条回复）——
              // 后端原样记录，所以回复一条回复是允许的
              parentId={comment.id}
              placeholder={`回复 ${comment.author_display_name}…`}
              onDone={() => setReplying(false)}
              onCancel={() => setReplying(false)}
            />
          </div>
        )}
      </div>

      {comment.replies.length > 0 && (
        <div>
          {comment.replies.map((reply) => (
            <CommentItem
              key={reply.id}
              comment={reply}
              postId={postId}
              interactionsOpen={interactionsOpen}
              // 真实层级一路往下传，不封顶：缩进是否叠加由上面的 wrapperClass 决定。
              // ⚠️ 不要写成 Math.min(depth + 1, 1)——那样视觉上虽然也对，
              //    但 depth 就不再是「这是第几层」，以后想按层级做别的事
              //    （折叠、只给第一层加左边框）就无从判断了。
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </article>
  )
}
