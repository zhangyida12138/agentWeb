import { useState } from 'react'

import { Alert } from '../../components/Alert'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'

import { CommentForm } from './CommentForm'
import { CommentItem } from './CommentItem'
import { useCommentsQuery } from './hooks'
import { canCreateComment } from './permissions'

import type { CommentPage } from './types'

/**
 * 一篇文章的评论区。
 *
 * 这个组件是评论模块**唯一**持有列表查询的地方：
 *   `CommentItem` 是纯渲染 + 单条写操作，绝不自己调 `useCommentsQuery`——
 *   每条评论各自持有一份列表查询看起来也能跑，但那意味着 10 条评论就有 10 个观察者，
 *   任何一次失效都要冲刷 10 遍，且每条的 loading 状态互相独立
 *   （表现是「新评论长出来时下面几条闪了一下」）。
 *
 * 分页单位是「一段对话」（一条根评论 + 它的全部回复），
 * 所以这里的 `total` 是根评论数，文案必须写「段对话」而不是「条评论」。
 * 那个「一共有多少条评论」的数字在 `PostInteractionBar` 上，
 * 来自另一个接口（`comment_count` 是根 + 回复的总数）。
 *
 * ⚠️ 这个查询**不**依赖登录状态：评论公开可读，匿名访客也要能看到。
 *    所以绝不要写成 `enabled: Boolean(user)`——那会让游客看到空评论区，
 *    同时后端白白暴露一个「不需要认证的接口被前端拒之门外」的错觉。
 *    同理，这里**不**调用任何会 401 的接口（比如 /auth/me）。
 */

const PAGE_SIZE = 10

interface CommentTreeProps {
  postId: string
  /** 文章是否接受新的互动（已发布）。草稿/已下架时隐藏发表框、禁用点赞。 */
  interactionsOpen: boolean
}

export function CommentTree({ postId, interactionsOpen }: CommentTreeProps) {
  const [offset, setOffset] = useState(0)

  const { user } = useAuth()
  const accessQuery = useMyAccessQuery({ enabled: Boolean(user) })
  const codes = accessQuery.data?.permission_codes

  const query = useCommentsQuery(postId, { offset, limit: PAGE_SIZE })
  const page: CommentPage | undefined = query.data

  const total = page?.total ?? 0
  const itemCount = page?.items.length ?? 0
  const hasPrevious = offset > 0
  const hasNext = offset + itemCount < total

  return (
    <section className="flex flex-col gap-4">
      <header className="flex items-baseline gap-3">
        <h2 className="text-lg font-semibold text-gray-900">评论</h2>
        <span className="text-xs text-gray-500">{total} 段对话</span>
      </header>

      {canCreateComment(codes) && interactionsOpen && <CommentForm postId={postId} />}

      {!user && <p className="text-sm text-gray-500">登录后可以参与讨论。</p>}

      {!interactionsOpen && user && (
        <p className="text-sm text-gray-500">文章已下架，不再接受新的评论。</p>
      )}

      {query.isError && (
        <Alert tone="error">
          {query.error instanceof Error ? query.error.message : '评论加载失败'}
        </Alert>
      )}

      {query.isPending && <p className="text-sm text-gray-500">正在加载评论…</p>}

      {page && itemCount === 0 && (
        <p className="text-sm text-gray-500">还没有评论，来说第一句吧。</p>
      )}

      <div className="flex flex-col gap-4">
        {page?.items.map((comment) => (
          /*
                      key 里带上 offset：翻页时同一篇文章的评论会整体换一批，
                      用纯 id 做 key 时 React 会尝试复用上一页的 DOM 节点，
                      而「正在回复哪一条」这类本地状态是挂在节点上的——复用的结果
                      是上一页那条的回复框跑到了这一页某条评论下面。
                    */
          <CommentItem
            key={`${offset}:${comment.id}`}
            comment={comment}
            postId={postId}
            interactionsOpen={interactionsOpen}
          />
        ))}
      </div>

      {total > PAGE_SIZE && (
        <nav className="flex items-center justify-between border-t border-gray-100 pt-4 text-sm">
          <span className="text-gray-500">
            第 {Math.floor(offset / PAGE_SIZE) + 1} / {Math.ceil(total / PAGE_SIZE)} 段 · 共 {total}{' '}
            段对话
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={!hasPrevious || query.isFetching}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              上一页
            </button>
            <button
              type="button"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={!hasNext || query.isFetching}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              下一页
            </button>
          </div>
        </nav>
      )}
    </section>
  )
}
