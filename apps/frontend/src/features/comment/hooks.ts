import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { likeKeys, toggleLike } from '../like/api'
import { LIKE_TARGET_TYPE } from '../like/types'

import { commentKeys, createComment, deleteComment, fetchComments } from './api'
import { patchCommentLike } from './tree'

import type { PostInteractionStats } from '../like/types'
import type { CommentListParams, CommentPage, CreateCommentInput } from './types'

/**
 * 评论模块的数据钩子。
 *
 * 这里的写操作分成两类，收尾方式**刻意不同**：
 *
 *   点赞 → **就地改缓存**（`patchCommentLike`）。
 *     响应里带着权威的赞数与状态，没有任何东西需要重新请求；
 *     重新拉一次列表会让整棵评论树闪一下，而这只是点了一个小按钮。
 *
 *   发表 / 撤回 → **失效列表**。
 *     这两种操作都改变了「树里有几个节点、分页总数是多少」，
 *     而新评论会落在哪一页取决于排序方向（后端按 created_at 升序，
 *     新评论在**最后一页**），前端要自己算清楚「该把它插到第几页的第几位」
 *     等于把后端的排序规则抄一遍——抄错了就是「评论发出去了但页面上看不到」。
 *     评论区是低频操作，多一次 GET 完全值得。
 */

/**
 * 评论列表。
 *
 * `enabled` 由调用方按「文章是否已经加载出来」控制：postId 来自详情响应，
 * 没拿到之前发请求会打到 `/posts/undefined/comments`（后端回 40000，
 * 而前端会把它当成一次真实失败去展示，用户一进页面就先看到一条红字）。
 *
 * `staleTime` 给 15 秒（比文章短）：评论是别人也在写的内容，
 * 但它比文章更新得频繁得多，缓存久了会出现「刚回复完刷新一下回复不见了」。
 */
export function useCommentsQuery(postId: string | undefined, params: CommentListParams = {}) {
  return useQuery({
    queryKey: commentKeys.listPage(postId ?? '', params),
    queryFn: () => fetchComments(postId as string, params),
    enabled: Boolean(postId),
    staleTime: 15 * 1000,
    // 翻页时先显示上一页，列表不会在切换瞬间塌成空白再长出来
    placeholderData: keepPreviousData,
  })
}

/**
 * 给统计缓存里的评论数加一个增量。
 *
 * ⚠️ 这里**跨模块**引用了 `features/like/api` 的 `likeKeys`，这是有意的：
 *     「赞数 + 评论数」在后端由同一个接口（`GET /posts/{id}/interactions`）
 *     一并返回，所以它们在前端也必须是同一条缓存记录。
 *     若把评论数单独存一份 key，这条记录就有两个半区分别由两个模块写，
 *     一定会出现「点完赞之后评论数被覆盖成 0」这种半区互相踩踏的现象。
 *
 * 缓存里没有这条记录时返回 undefined（不创建）——凭一个增量造不出完整的记录，
 * `like_count` 和 `liked_by_me` 都是未知的，硬填 0/false 会显示错。
 */
function bumpPostCommentCount(
  queryClient: ReturnType<typeof useQueryClient>,
  postId: string,
  delta: number,
): void {
  queryClient.setQueryData<PostInteractionStats>(likeKeys.postStats(postId), (previous) =>
    previous
      ? { ...previous, comment_count: Math.max(0, previous.comment_count + delta) }
      : undefined,
  )
}

/**
 * 发表评论 / 回复。
 *
 * 成功后做两件事：
 *   ① 失效这一篇文章的评论列表（含全部页码）——树变了，位置由后端定；
 *   ② 把统计里的评论数 +1。
 * ② 能就地算出来是因为**一次发表恰好只产生一条评论**，
 * 无论它是根评论还是回复（`comment_count` 两者都算）。
 */
export function useCreateCommentMutation(postId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateCommentInput) => createComment(postId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: commentKeys.list(postId) })
      bumpPostCommentCount(queryClient, postId, 1)
    },
  })
}

/**
 * 撤回评论。
 *
 * 这里**不**就地减一，而是失效统计缓存。理由：
 *   撤回一条**有回复的根评论**会把它自己变成墓碑（仍在树上），
 *   所以到底少了几条评论（0 条 / 1 条 / 更多）取决于它的回复情况，
 *   而 204 响应里没有任何信息可以用来判断。
 *   与其猜一个数出来（猜错就是这个数字从此长期是错的），
 *   不如让服务端再算一次——一次 GET 而已。
 */
export function useDeleteCommentMutation(postId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (commentId: string) => deleteComment(commentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: commentKeys.list(postId) })
      void queryClient.invalidateQueries({ queryKey: likeKeys.postStats(postId) })
    },
  })
}

/**
 * 给评论点赞 / 取消点赞。
 *
 * 用 `setQueriesData` 把结果 patch 进**这篇文章的所有评论页**，
 * 而不只是当前这一页：用户可能点完赞就翻页回去了，缓存里其他几页
 * 还留着旧数字的话，回去时会看到「刚才明明赞过了，怎么又变回未赞」。
 *
 * 目标评论不在缓存里时（比如点在了一个早已被撤回、只因为这页缓存没刷新
 * 才还在屏幕上的评论），`patchCommentLike` 会原样返回同一个对象，
 * 缓存不变、也不报错。
 */
export function useToggleCommentLikeMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ commentId }: { postId: string; commentId: string }) =>
      toggleLike({ target_type: LIKE_TARGET_TYPE.COMMENT, target_id: commentId }),
    onSuccess: (state, variables) => {
      queryClient.setQueriesData<CommentPage>(
        { queryKey: commentKeys.list(variables.postId) },
        (page) =>
          page
            ? patchCommentLike(page, {
                commentId: state.target_id,
                likeCount: state.like_count,
                liked: state.liked,
              })
            : page,
      )
    },
  })
}
