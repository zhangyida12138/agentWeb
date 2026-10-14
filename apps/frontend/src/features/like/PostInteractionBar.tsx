import { useState } from 'react'

import { Alert } from '../../components/Alert'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'
import { PERMISSION, hasPermission } from '../access/permissions'

import { usePostInteractionStatsQuery, useTogglePostLikeMutation } from './hooks'
import { LikeButton } from './LikeButton'
import { LIKE_TARGET_TYPE } from './types'

/**
 * 文章详情页的互动条：点赞按钮 + 评论总数。
 *
 * 为什么单独一个组件而不是写在 PostDetailPage 里：
 *   这一条依赖两个**异步**数据源（互动统计、当前用户的权限集），
 *   而 PostDetailPage 在文章没加载出来时会提前 return——把这一条提到页面里，
 *   那些 `useQuery` 就不得不在「文章还不知道是什么」的状态下先跑起来。
 *   独立成子组件后，它只在文章真的加载出来之后才挂载，
 *   内部就可以放心地假设 postId 是有效的。
 *
 * 为什么这里要自己再调一次 `useMyAccessQuery`：
 *   和 PostDetailPage 里那次是**同一个 queryKey**，React Query 会去重，
 *   只发一次请求。让组件自带它真正需要的数据，比从父组件传 4 个 prop
 *   （codes / user / stats / mutation）更不容易漏——而后者的漏法是
 *   「管理员看到的按钮是灰的」，只有那个角色能复现。
 */

interface PostInteractionBarProps {
  postId: string
  /**
   * 这篇文章是否接受新的互动（已发布）。
   *
   * 草稿与已归档都**不接受**新互动：后端会回 40940。
   * 但按钮不隐藏、只禁用，因为**已有的赞仍然显示**——
   * 隐藏掉会让人以为「赞被清空了」，而实际上只是不能再加。
   */
  interactionsOpen: boolean
}

export function PostInteractionBar({ postId, interactionsOpen }: PostInteractionBarProps) {
  const { user } = useAuth()
  const accessQuery = useMyAccessQuery({ enabled: Boolean(user) })
  const codes = accessQuery.data?.permission_codes

  const statsQuery = usePostInteractionStatsQuery(postId)
  const likeMutation = useTogglePostLikeMutation()
  const [actionError, setActionError] = useState<string | null>(null)

  const stats = statsQuery.data

  /** 未登录 / 无权限 / 文章已下架 —— 三种禁用原因按「先决条件」的顺序判断。 */
  function disabledReason(): string | undefined {
    if (!user) return '登录后可点赞'
    if (!hasPermission(codes, PERMISSION.LIKE_TOGGLE)) return '你没有「like:toggle」权限'
    if (!interactionsOpen) return '文章已下架，不再接受新的点赞'
    return undefined
  }

  const handleToggle = async () => {
    setActionError(null)
    try {
      await likeMutation.mutateAsync({
        target_type: LIKE_TARGET_TYPE.POST,
        target_id: postId,
      })
    } catch (error) {
      // 40940（文章已下架）：按钮的禁用状态来自上一个渲染周期里读到的 status，
      // 而作者可能刚在另一个标签页里下架了这篇文章。就地提示，不整页替换——
      // 文章内容本身是好的，不该被一个失败按钮带走。
      setActionError(error instanceof ApiError ? error.message : '操作失败')
    }
  }

  const reason = disabledReason()

  return (
    <div className="flex flex-col gap-3">
      {actionError && <Alert tone="error">{actionError}</Alert>}

      <div className="flex flex-wrap items-center gap-4 border-t border-gray-100 pt-4">
        <LikeButton
          liked={stats?.liked_by_me ?? false}
          likeCount={stats?.like_count ?? 0}
          isPending={likeMutation.isPending}
          // 统计还没回来时按钮也是禁用的：此刻 liked 可能是错的
          // （缓存里没有数据 → liked 默认 false），让人点下去等于用错状态发请求
          disabled={reason !== undefined || !stats}
          disabledReason={reason}
          onToggle={() => void handleToggle()}
        />

        {/*
          这里用的是**评论总数**（根评论 + 回复），所以文案写「评论 N 条」；
          下面评论区的分页单位是「段对话」，用的是**根评论数**，文案另外写。
          两个数来自两个接口，口径不同，文案必须跟着不同——
          混着写就会出现「上面说 8 条评论、下面只有 3 段对话」这种看起来像 bug 的现象。
        */}
        <span className="text-sm text-gray-500">评论 {stats ? stats.comment_count : '—'} 条</span>
      </div>
    </div>
  )
}
