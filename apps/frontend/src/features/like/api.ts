import { request } from '../../lib/api'

import type { LikeState, PostInteractionStats, ToggleLikeInput } from './types'

/**
 * 点赞模块的接口封装。
 *
 * 只有两个接口，但它们的职责差别很大，值得写清楚：
 *
 *   `GET /posts/{id}/interactions` 是**只读**的初值来源。
 *     它存在的唯一理由是：按钮在用户点之前就必须显示正确状态。
 *     只靠 toggle 的响应也能拿到「点完之后」的状态，但第一次点击之前呢？
 *     答案是「不知道」——于是所有登录用户一进页面看到的就是 0 赞 / 未点赞，
 *     而已赞的人点一下其实是**取消**。这个接口就是为了消掉那段说谎的时间。
 *
 *   `POST /likes/toggle` 是**写**接口，且刻意不叫 `/likes` + `{liked: true}`：
 *     由客户端指定目标状态，就得让客户端先读一次状态再发请求，
 *     两次请求之间的状态可能已经变了——那正是「我点的明明是赞，结果变成了取消」的成因。
 *     服务端握着权威状态，就该让它来决定方向。
 *
 * ⚠️ 统计接口在后端由 `endpoints/likes.py` 提供（与 toggle 同一个模块），
 *    前端也放在 like 模块里，两边的归属保持一致。
 *    它同时也是**评论数**的来源，所以 `features/comment/hooks.ts` 会跨模块
 *    引用下面这个 `likeKeys`——那处引用是有意的，理由写在那里。
 */

/** 切换某个目标的点赞状态（需要 `like:toggle` 权限，登录用户默认持有）。 */
export function toggleLike(input: ToggleLikeInput): Promise<LikeState> {
  return request<LikeState>('/likes/toggle', { method: 'POST', body: input })
}

/**
 * 读一篇文章的互动统计（公开，无需登录；游客的 `liked_by_me` 恒为 false）。
 *
 * 后端对未知 / 未发布的 id **不报 404**，而是回一组 0：
 * 这个接口会被放在「文章可见就渲染」的位置上，若它对草稿报 404，
 * 作者预览自己的草稿时就会看到一个加载失败的红条——
 * 而实际上「还没有人赞过」才是那个场景下的正确答案。
 */
export function fetchPostInteractionStats(postId: string): Promise<PostInteractionStats> {
  return request<PostInteractionStats>(`/posts/${postId}/interactions`)
}

/**
 * queryKey 工厂。
 *
 * 只有一棵树、按 post_id 分片，和 `postKeys.detail` 按 slug 分片刚好相反：
 *   详情用 slug 是因为**入口**只有 slug（路由参数就是它）；
 *   统计用 id 是因为**写入**只有 id（toggle 的响应里给的是 target_id）——
 *   按 slug 缓存的话，点赞成功后要先把 id 反查成 slug 才能写缓存，
 *   而这个反查正是我们不想维护的映射。
 */
export const likeKeys = {
  statsRoot: ['like', 'stats'] as const,
  postStats: (postId: string) => [...likeKeys.statsRoot, postId] as const,
}
