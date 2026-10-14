/**
 * 权限点常量：与后端 `app/domain/access/entities.py::PermissionCode` 一一对应。
 *
 * 为什么要手抄一份常量，而不是「后端给什么就信什么」：
 *   页面要判断「有没有 user:list」，就得拿一个字符串去比对。写成裸字符串
 *   一定会出现 `'user:list '`（多一个空格）这种拼错——它不报错，
 *   只是判断永远为 false，表现为「明明有权限却不显示入口」，排查很费时。
 *   收进常量后，拼错在编译期就被 IDE 抓出来。
 *
 * ⚠️ 判断依据必须是**权限码**，不能用角色名（`role_codes.includes('admin')`）：
 *    角色可以新增、可以改名、可以出现「有权限但没有 admin 这个角色名」的自定义角色，
 *    而接口守卫校验的永远是权限码。两边用同一把尺子，才不会出现
 *    「按钮给了、一点就 403」的错位。
 *
 * ⚠️ 后端新增权限点时，这个对象**必须同步新增**，否则前端永远匹配不上。
 */

export const PERMISSION = {
  USER_LIST: 'user:list',
  USER_ASSIGN_ROLES: 'user:assign_roles',
  USER_RESET_PASSWORD: 'user:reset_password',
  ROLE_LIST: 'role:list',
  POST_CREATE: 'post:create',
  POST_UPDATE: 'post:update',
  POST_PUBLISH: 'post:publish',
  POST_DELETE: 'post:delete',
  // 这两个是「越过 owner 判定」的越权位，和上面四个不是一回事：
  //   post:update / post:delete 是**入场券**——没有它连作者自己的文章都改不了；
  //   post:*_any           是**免检牌**——有它才能改别人的文章。
  // 后端两把尺子是分开的（守卫一次、实体一次），前端也必须是两步判断，
  // 详见 features/post/permissions.ts。
  POST_UPDATE_ANY: 'post:update_any',
  POST_DELETE_ANY: 'post:delete_any',
  // ── 互动（M5） ──
  // 和文章那四项一一对应，连「入场券 / 免检牌」的分法都一样：
  //   comment:delete 是入场券（reader 就持有，删自己的评论是默认能力）；
  //   comment:delete_any 是免检牌（仅 admin，用于删别人的违规内容）。
  // 中间故意**没有** comment:update：评论一旦发出就不能改，
  // 想改只能撤回再发——这条产品规则让「编辑评论」的权限点根本不存在。
  COMMENT_CREATE: 'comment:create',
  COMMENT_DELETE: 'comment:delete',
  COMMENT_DELETE_ANY: 'comment:delete_any',
  LIKE_TOGGLE: 'like:toggle',
} as const

export type PermissionCode = (typeof PERMISSION)[keyof typeof PERMISSION]

/**
 * 当前用户的权限集里有没有某一项。
 *
 * `codes` 允许为 undefined，因为 `/auth/me/access` 是异步加载的：
 * 加载完成前权限未知。此时返回 false（**默认拒绝**），
 * 与后端「没查到权限就 403」的口径一致——
 * 反过来写（未知时放行）会让加载期间闪出一个马上会 403 的按钮。
 */
export function hasPermission(codes: readonly string[] | undefined, code: PermissionCode): boolean {
  return codes?.includes(code) ?? false
}

/**
 * 权限集里有没有其中**任意一项**。
 *
 * 用来表达「满足其一即可」的入口，例如「写文章」按钮：
 * `post:create` 能发新文，而拥有 `post:update_any` 的管理员即便没有
 * post:create 也应该能进编辑器改别人的文章。写成 `hasPermission(a) || hasPermission(b)`
 * 也能跑，但那个 `||` 每处都要重写一遍，漏一处就是一种「权限有的用户看不见入口」的怪现象。
 */
export function hasAnyPermission(
  codes: readonly string[] | undefined,
  required: readonly PermissionCode[],
): boolean {
  return required.some((code) => hasPermission(codes, code))
}
