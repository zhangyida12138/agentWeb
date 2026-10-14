import { PERMISSION, hasPermission } from '../access/permissions'

import type { CommentNode } from './types'

/**
 * 「这条评论我愿意让你删吗」的唯一实现。
 *
 * 和后端 `domain/interaction/entities.py::Comment.ensure_deletable_by` 一一对应，
 * 也是同一条**两把尺子**的规矩（与 `features/post/permissions.ts` 完全同构）：
 *   ① 能力尺：接口守卫要求 `comment:delete`，没有就 40320；
 *   ② 归属尺：能力有了之后还要看这条是不是你写的，不是就 40340，
 *      除非你另持有 `comment:delete_any` 这把免检牌（后端只给 admin）。
 *
 * 为什么单独一个文件：详情页（文章删除）已经踩过一次这个坑——
 * 把两把尺子合并成 `comment.author_id === me`，管理员就看不到删除按钮，
 * 而接口其实允许他删；反过来漏掉归属判断，则人人可见按钮、一按就 40320。
 * 两种错位都只在特定角色下暴露，所以判断只能有一份实现。
 *
 * ⚠️ 这里算出来的是**界面可见性**，不是安全边界。
 */

/** 能不能发表评论 / 回复（能力：`comment:create`；reader 默认持有）。 */
export function canCreateComment(codes: readonly string[] | undefined): boolean {
  return hasPermission(codes, PERMISSION.COMMENT_CREATE)
}

/** 能不能点赞（能力：`like:toggle`；**未登录一律不能**，点赞是一人一票的记录）。 */
export function canToggleLike(codes: readonly string[] | undefined): boolean {
  return hasPermission(codes, PERMISSION.LIKE_TOGGLE)
}

/** 判断「这条评论是不是当前用户写的」。未登录（无 id）时一律 false。 */
export function isCommentAuthor(
  comment: Pick<CommentNode, 'author_id'>,
  currentUserId: string | undefined,
): boolean {
  if (!currentUserId) return false
  return comment.author_id === currentUserId
}

/**
 * 能不能删这条评论：能力（`comment:delete`）+ 归属（本人 或 `comment:delete_any`）。
 *
 * 已撤回的评论一律 false：后端把所有入口的「已撤回」都当成「不存在」，
 * 再删一次会 40440。界面提前把按钮收掉，用户就不会点出一个「删除失败」
 * 却其实是「早就删掉了」的提示。
 */
export function canDeleteComment(
  codes: readonly string[] | undefined,
  comment: Pick<CommentNode, 'author_id' | 'is_deleted'>,
  currentUserId: string | undefined,
): boolean {
  if (comment.is_deleted) return false
  if (!hasPermission(codes, PERMISSION.COMMENT_DELETE)) return false
  return (
    isCommentAuthor(comment, currentUserId) || hasPermission(codes, PERMISSION.COMMENT_DELETE_ANY)
  )
}
