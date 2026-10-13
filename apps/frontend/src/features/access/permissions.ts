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
