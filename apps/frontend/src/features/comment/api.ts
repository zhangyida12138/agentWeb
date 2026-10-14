import { request } from '../../lib/api'

import type { CommentListParams, CommentNode, CommentPage, CreateCommentInput } from './types'

/**
 * 评论模块的接口封装。
 *
 * 三个接口的路径形状不一样，这不是随意的，值得写清楚：
 *
 *   `GET|POST /posts/{post_id}/comments` —— 挂在**文章**下面。
 *     评论列表天然是「某篇文章的评论区」，挂在文章下让这个从属关系出现在路径里，
 *     而不是藏在 query 参数里。
 *
 *   `DELETE /comments/{comment_id}` —— 挂在自己的顶层。
 *     删除的入参是评论 id，调用方手上正好有它；
 *     若写成 `/posts/{post_id}/comments/{id}`，调用方还得额外知道自己正处在哪篇文章里，
 *     而评论 id 本身已经是全局唯一的了——多要一个参数就是多一个能对不上的地方。
 *
 * ⚠️ 全部用 `post_id` 而不是 slug：slug 是文章的**可改**属性，
 *    用它当键会让「改永久链接」顺带影响评论缓存，而评论和 slug 没有任何关系。
 *    （对比 `features/post/api.ts`：那里读详情用 slug，因为详情页的入口就是 slug。）
 */

/**
 * 读一篇文章的评论树（公开，无需登录）。
 *
 * `total` / `offset` / `limit` 都是服务端收敛后的值，不要用手上传的那份算总页数，
 * 理由同文章列表。
 */
export function fetchComments(
  postId: string,
  { offset, limit }: CommentListParams = {},
): Promise<CommentPage> {
  const search = new URLSearchParams()
  if (offset !== undefined) search.set('offset', String(offset))
  if (limit !== undefined) search.set('limit', String(limit))
  const query = search.toString()

  return request<CommentPage>(
    `/posts/${encodeURIComponent(postId)}/comments${query ? `?${query}` : ''}`,
  )
}

/**
 * 发表评论或回复。
 *
 * 后端回 **201 + 这条新评论**（不是 204、也不是整个列表）。
 * 但前端拿到它之后仍然会失效整个评论列表，而不是把它插进缓存——
 * 理由写在 `hooks.ts::useCreateCommentMutation` 里（排序方向决定新评论落在哪一页）。
 */
export function createComment(postId: string, input: CreateCommentInput): Promise<CommentNode> {
  return request<CommentNode>(`/posts/${encodeURIComponent(postId)}/comments`, {
    method: 'POST',
    body: input,
  })
}

/**
 * 撤回评论（软删除，**不是**物理删除）。后端回 204。
 *
 * 撤回之后这条评论还在数据里，只是内容不再返回；它的回复也仍然挂在那里。
 * 所以前端删完不能以为「树里少了这个节点」——列表刷新后可能还能看到它，
 * 只是变成了墓碑。这正是这里返回 `Promise<void>` 却仍然要重新拉列表的原因。
 */
export function deleteComment(commentId: string): Promise<void> {
  return request<void>(`/comments/${encodeURIComponent(commentId)}`, { method: 'DELETE' })
}

/**
 * queryKey 工厂。
 *
 * 和 `postKeys` 一样分成「根 / 列表 / 分页」三层，原因也一样：
 *   失效的范围在调用点一眼可读。评论的失效范围特别小（只影响一篇文章的评论区），
 *   所以 `list(postId)` 这一层是**用 setQueriesData patch 全部页码**的抓手——
 *   点赞一条评论时我们并不想重新请求，只想改掉它在那几页里的两个字段。
 */
export const commentKeys = {
  root: ['comment'] as const,
  list: (postId: string) => [...commentKeys.root, 'list', postId] as const,
  listPage: (postId: string, params: CommentListParams) =>
    [...commentKeys.list(postId), params.offset ?? 0, params.limit ?? 0] as const,
}
