import { PERMISSION, hasPermission } from '../access/permissions'

import type { Tag } from './types'

/**
 * 标签的「能不能看见 / 能不能点」判断，全部收在这个文件里。
 *
 * ── 先声明一条底线 ──
 * 这里返回的每一个布尔值都**只是界面可见性**，不是安全边界。
 * 真正的裁决在后端，而且是**两层**、位置各不相同：
 *
 *   ① 路由守卫 `require_permission(PermissionCode.TAG_MANAGE)`
 *      —— 挂在 POST / PATCH /{id}/status / DELETE 三条路由上，
 *         回答「**你这个身份**能不能碰术语表本身」。不满足直接 403，用例根本不会执行。
 *   ② 领域实体 `Tag.ensure_manageable_by(actor_id, actor_can_manage_any)`
 *      —— 只挂在 PUT 一条路由上，回答「**这一个**标签是不是你的」。
 *         它按 type 和 author_id 分支出 40051（系统标签谁都改不了）/ 40350（是别人的）。
 *
 * 前端这里能做的只有「把不该出现的入口藏起来」。藏起来不等于挡住了：
 * 直接构造请求打后端，该 403 还是 403。**这一层存在的意义是
 * 让用户不必先撞一次墙才知道自己没资格。**
 *
 * ── 为什么判定必须以「行」为单位，而不是「页」为单位 ──
 * PUT /tags/{id} 是唯一一条**没有路由守卫**的写接口（见后端 endpoints/tag.py 的说明）。
 * 也就是说「我有没有编辑标签的资格」这个问题**根本没有全局答案**：
 *   管理员对 user 标签是「有」，对 system 标签是「没有」；
 *   普通作者对自己建的标签是「有」，对别人的是「没有」。
 * 所以下面所有函数的第一参数都是某个具体的 `Tag`，而不是一串 codes。
 */

/**
 * 能不能管理术语表（新建 / 下架 / 删除 / 改任意用户标签）。
 *
 * 单个权限点，没有 `*_any` 的配对——`tag:manage` 本身就是那把越权钥匙。
 * 这与 post 的 `post:delete` + `post:delete_any` 两层结构不同，
 * 原因见 access/permissions.ts 里的说明。
 */
export function canManageTags(codes: readonly string[] | undefined): boolean {
  return hasPermission(codes, PERMISSION.TAG_MANAGE)
}

/**
 * 这个标签是不是当前用户创建的。
 *
 * `tag.author_id === null`（存量数据 / 创建者已注销）时必须返回 **false**：
 * 无主标签只有拿 `tag:manage` 的人能动，后端对它一律 40350。
 * 写成 `tag.author_id !== currentUserId` 取反的写法在这里会出错——
 * `null !== userId` 是 true，于是无主标签会被判成"不是我的"，
 * 恰好也是 false，结果凑对了；但读代码的人会以为「有个主人，只是不是我」，
 * 把「无主」这个真实存在的状态藏起来。**结论相同不代表两种写法等价。**
 */
export function isTagAuthor(tag: Tag, currentUserId: string | undefined): boolean {
  if (!tag.author_id || !currentUserId) return false
  return tag.author_id === currentUserId
}

/**
 * 能不能编辑这个标签（改名 / 改描述）。
 *
 * 四条判断，顺序与后端 `Tag.ensure_manageable_by` **保持一致**——顺序在这里不是风格问题：
 *   ① 已删除 → 一律不能。后端 `ensure_not_deleted()` 对已删除的标签回 **404**，
 *      而不是"改不了"。404 的意思是「这个东西不存在」，所以界面上也不该
 *      还留着一个能点的编辑入口。
 *   ② system 类型 → 只有管理员能改。这一条必须先于归属判断：
 *      系统标签是平台预置的首页入口，对普通用户正确的回答是
 *      「它谁都不能改」（40051），而不是「它是别人的」（40350）——
 *      后者会让人去找管理员要权限，而正确答案是要了也没用。
 *   ③ 管理员 → 放行一切未删除的标签（越权钥匙）。
 *   ④ 登录用户 + 是我建的 → 放行。
 *
 * ⚠️ 第 ④ 条隐含一个大前提：**必须已登录**。`currentUserId` 为 undefined 时
 *    第 ③ ④ 两条都会落空（`canManageTags(undefined)` 返回 false），
 *    于是游客拿到的一切都是不可编辑——这正是我们要的。
 *    但它依赖「未登录时 codes 也是 undefined」这一事实成立；
 *    若将来有人让游客带上了一份权限快照，这里必须显式补一条登录判断。
 */
export function canEditTag(
  codes: readonly string[] | undefined,
  tag: Tag,
  currentUserId: string | undefined,
): boolean {
  if (tag.status === 'deleted') return false

  const manageAny = canManageTags(codes)
  if (tag.type === 'system') return manageAny

  if (manageAny) return true
  return isTagAuthor(tag, currentUserId)
}

/**
 * 能不能改状态（下架 / 恢复 / 取消删除）。
 *
 * 只认权限，不看归属：标签的启停是术语表治理动作，
 * 作者能改自己标签的**名字**，但不能自己把标签从公开列表里撤掉——
 * 那会让别人已发布的文章上挂着的标签突然消失。
 *
 * 对**已删除**的标签也返回 true：这是唯一的恢复入口
 * （后端 `ChangeTagStatusUseCase` 刻意不调 `ensure_not_deleted`）。
 */
export function canChangeTagStatus(codes: readonly string[] | undefined): boolean {
  return canManageTags(codes)
}

/**
 * 能不能删除（软删除）这个标签。
 *
 * 已经删除的行返回 false：DELETE 本身是幂等的（再删一次也回 204），
 * 但给一个已删除的标签显示「删除」按钮是纯误导——
 * 用户会以为上一步没生效，然后对着一个灰按钮反复点。
 * 那一行的正确操作是「恢复」。
 */
export function canDeleteTag(codes: readonly string[] | undefined, tag: Tag): boolean {
  if (tag.status === 'deleted') return false
  return canManageTags(codes)
}

/**
 * 能不能在标签列表里看到非正常状态的标签。
 *
 * 普通读者看标签列表时，界面只露出「正常」这一档：
 * 「已下架」对他是噪音（他既不能恢复也不能删除），
 * 而「已删除」的后端语义是「对所有读路径不可见」——
 * 给读者开一个能看到已删除标签的入口，等于亲手把那条语义破了。
 * 管理员要审阅垃圾数据，那是管理页的事。
 */
export function canSeeAllTagStatuses(codes: readonly string[] | undefined): boolean {
  return canManageTags(codes)
}
