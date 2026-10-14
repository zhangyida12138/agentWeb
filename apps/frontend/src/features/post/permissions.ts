import { PERMISSION, hasPermission } from '../access/permissions'

import type { PostSummary } from './types'

/**
 * 「这篇我愿意让你改吗」的唯一实现。
 *
 * 为什么要单独一个文件、而不是在列表页和详情页各写一遍 `post.author_id === me`：
 *   后端的判断是**两把尺子**（见 `domain/blog/entities.py::ensure_owned_by`）：
 *     ① 能力尺：接口守卫要求 `post:update`，没有就 40320；
 *     ② 归属尺：能力有了之后还要看这篇是不是你的，不是就 40330，
 *        除非你另持有 `post:update_any` 这把免检牌。
 *   前端如果把这两步合并成一句 `isAuthor`，管理员看到的会是「没有编辑按钮」，
 *   而接口其实允许他改——页面比接口更严，功能就凭空消失了；
 *   反过来（漏掉归属判断）则会出现「按钮人人可见、一按就 403」。
 *   两种错位都只在特定角色下才暴露，所以判断只能有一份实现。
 *
 * ⚠️ 这里算出来的是**界面可见性**，不是安全边界。
 *    真正的鉴权在后端守卫与用例上；前端少显示一个按钮拦不住任何人。
 */

/** 判断「这篇是不是当前用户写的」。未登录（无 id）时一律 false。 */
export function isPostAuthor(
  post: Pick<PostSummary, 'author_id'>,
  currentUserId: string | undefined,
): boolean {
  if (!currentUserId) return false
  return post.author_id === currentUserId
}

/**
 * 能不能进编辑器写新文章。
 *
 * `post:update_any` 也算：管理员即便没有 `post:create`（那是作者角色的权限点），
 * 也该能打开编辑器改别人的文章。把「新建入口」的可见性绑死在单一权限码上，
 * 会出现「能改别人的文章，却看不见编辑入口」这种自相矛盾的界面——
 * 而那个管理员的 `post:update` 是有的，接口也确实会放行。
 */
export function canCreatePost(codes: readonly string[] | undefined): boolean {
  return (
    hasPermission(codes, PERMISSION.POST_CREATE) || hasPermission(codes, PERMISSION.POST_UPDATE_ANY)
  )
}

/** 能不能编辑这一篇：能力（post:update）+ 归属（本人 或 post:update_any）。 */
export function canEditPost(
  codes: readonly string[] | undefined,
  post: Pick<PostSummary, 'author_id'>,
  currentUserId: string | undefined,
): boolean {
  if (!hasPermission(codes, PERMISSION.POST_UPDATE)) return false
  return isPostAuthor(post, currentUserId) || hasPermission(codes, PERMISSION.POST_UPDATE_ANY)
}

/**
 * 能不能发布 / 下架。
 *
 * 能力用的是 `post:publish`（**不是** post:update），归属则复用 `post:update_any`：
 *   后端有意不为发布单开一个 `post:publish_any`——发布/下架和编辑一样都是
 *   「改动这篇文章」，用同一把钥匙可以避免管理员的开关散落成四五个近似权限码。
 *   前端必须跟着用同一把，否则会出现「接口允许下架、界面不给按钮」的错位。
 */
export function canPublishPost(
  codes: readonly string[] | undefined,
  post: Pick<PostSummary, 'author_id'>,
  currentUserId: string | undefined,
): boolean {
  if (!hasPermission(codes, PERMISSION.POST_PUBLISH)) return false
  return isPostAuthor(post, currentUserId) || hasPermission(codes, PERMISSION.POST_UPDATE_ANY)
}

/**
 * 能不能删除：能力用 `post:delete`，归属用 `post:delete_any`（**独立于**编辑）。
 *
 * 后端刻意把两把钥匙分开：删除不可逆，把它和编辑共用一把钥匙会让
 * 「我只想让人帮忙改错别字」顺带获得删光的能力。前端也必须分开，
 * 否则会出现「有编辑权就能看到删除按钮」的界面，而接口会 40320 拒掉它。
 */
export function canDeletePost(
  codes: readonly string[] | undefined,
  post: Pick<PostSummary, 'author_id'>,
  currentUserId: string | undefined,
): boolean {
  if (!hasPermission(codes, PERMISSION.POST_DELETE)) return false
  return isPostAuthor(post, currentUserId) || hasPermission(codes, PERMISSION.POST_DELETE_ANY)
}
