import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchPostInteractionStats, likeKeys, toggleLike } from './api'
import { LIKE_TARGET_TYPE } from './types'

import type { PostInteractionStats } from './types'

/**
 * 点赞模块的数据钩子。
 *
 * 缓存策略的核心只有一条：**toggle 的响应里带着权威答案，就地写回缓存，不要失效**。
 *   后端回的 `like_count` 是操作后的真实聚合值（不是 ±1 推出来的），
 *   `liked` 是操作后的真实状态，所以这两个数字没有任何需要重新请求的理由。
 *   反过来做（invalidate 一次）会带来两个问题：
 *     ① 点一下要等一次 GET 往返，按钮的反馈会「延迟半秒才变色」；
 *     ② 列表页上同时有多个按钮时，失效会让整片列表重新渲染。
 */

/**
 * 一篇文章的互动统计。
 *
 * `staleTime` 给 30 秒（与文章详情一致）：这个数字是别人点出来的，
 * 30 秒内不重拉是合理的；但也不能是 `Infinity`——
 * 用户从别的标签页切回来时，赞数应该会自己动一下。
 */
export function usePostInteractionStatsQuery(postId: string | undefined) {
  return useQuery({
    queryKey: likeKeys.postStats(postId ?? ''),
    queryFn: () => fetchPostInteractionStats(postId as string),
    // 路由还没匹配上时 postId 是 undefined，拦住它否则会请求 /posts/undefined/interactions
    enabled: Boolean(postId),
    staleTime: 30 * 1000,
  })
}

/**
 * 给文章点赞 / 取消点赞。
 *
 * 成功后**只**更新统计缓存里对应的那两个字段，不动 `comment_count`：
 * 本地算出来的是「赞数」，而 `comment_count` 是这条缓存的另一个半区，
 * 用 `{...prev}` 展开保留它，就不会把评论数顺手清成 0。
 *
 * 缓存里**没有**这条记录时（用户直接进详情页、统计请求还没回来就点了赞）
 * 更新函数返回 undefined，React Query 不会因此凭空创建一条数据——
 * 造一条假的出来就得自己填 `comment_count`，而那个数字我们并不知道。
 * 这种情况下按钮自身的 pending 状态会一直显示到那次 GET 返回为止。
 */
export function useTogglePostLikeMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: toggleLike,
    onSuccess: (state) => {
      // 这个 mutation 名义上是「给文章点赞」，但 mutationFn 是通用的 toggleLike，
      // 误传 target_type: 'comment' 时绝不能按文章去写缓存——那样会把评论的赞数
      // 写进某篇「id 恰好相同的文章」的统计里（id 都是 uuid，但类型上无从区分）。
      if (state.target_type !== LIKE_TARGET_TYPE.POST) return

      queryClient.setQueryData<PostInteractionStats>(
        likeKeys.postStats(state.target_id),
        (previous) =>
          previous
            ? { ...previous, like_count: state.like_count, liked_by_me: state.liked }
            : undefined,
      )
    },
  })
}
