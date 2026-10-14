import type { CommentNode, CommentPage } from './types'

/**
 * 评论树的纯函数工具箱。
 *
 * 单独一个模块、不放在 `hooks.ts` 里，是因为这里的东西是**纯的**：
 * 没有 React、没有网络、没有缓存，进出都是普通对象。
 * 于是它可以用普通单测（不用渲染、不用 QueryClient）覆盖到「回复三层嵌套」
 * 这类渲染测试里很难构造的边界，而 hooks 那边只剩下「接线」。
 *
 * 为什么需要「就地改缓存」而不是每次都重新拉列表：
 *   点赞一个按钮就重新请求整棵评论树，会让整片列表重新渲染并闪烁；
 *   而 toggle 的响应里已经带着权威的 `like_count` 与 `liked`，
 *   这两个值除了写进缓存之外无处可去。所以这里做的事就是
 *   「在一棵树里找到某个 id，改掉它的两个字段」。
 */

/** 就地改一个节点；没有变化时返回**原对象**，让 React Query 能靠引用相等跳过重渲染。 */
function patchNode(node: CommentNode, patch: CommentPatch): CommentNode {
  // 先递归子节点：目标可能在回复里（评论的赞和回复的赞存在同一张 likes 表里，
  // 从响应上根本分不出点的是哪一层，只能两处都找）
  const replies = node.replies.map((reply) => patchNode(reply, patch))
  const repliesChanged = replies.some((reply, index) => reply !== node.replies[index])

  if (node.id === patch.commentId) {
    return { ...node, like_count: patch.likeCount, liked_by_me: patch.liked, replies }
  }
  // 没找到目标、子节点也没变：直接把原对象还回去。
  // 这条分支决定了「点赞一个不在这页上的评论」不会导致整页重渲染。
  if (!repliesChanged) return node
  return { ...node, replies }
}

interface CommentPatch {
  commentId: string
  likeCount: number
  liked: boolean
}

/**
 * 把一次点赞的结果写进一页评论数据。
 *
 * 目标不在这页里时**原样返回同一个对象**——调用方（`setQueriesData`）
 * 会把这个返回值当成新的缓存值，返回原对象就等于「什么都没变」，
 * 不会触发任何订阅者重新渲染。
 */
export function patchCommentLike(page: CommentPage, patch: CommentPatch): CommentPage {
  const items = page.items.map((item) => patchNode(item, patch))
  const changed = items.some((item, index) => item !== page.items[index])
  return changed ? { ...page, items } : page
}

/**
 * 找出一页评论里所有的评论 id（含回复）。
 *
 * 现在只有测试在用，但它是「这页里有没有我要找的那条」这个问题的标准答案，
 * 所以留在模块里而不是写进测试文件：将来要加「批量查询这几个评论的点赞状态」
 * 时它就是那个入参构造函数。
 */
export function collectCommentIds(page: CommentPage): string[] {
  const ids: string[] = []
  const walk = (node: CommentNode) => {
    ids.push(node.id)
    node.replies.forEach(walk)
  }
  page.items.forEach(walk)
  return ids
}
