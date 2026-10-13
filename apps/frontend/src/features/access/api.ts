import { request } from '../../lib/api'
import type { AuthUser } from '../auth/types'

import type { AccessSummary, Role, UserPage } from './types'

/**
 * access 模块的接口封装。
 *
 * 只负责「拼路径、定类型」，不做任何缓存或状态（那是 hooks 的事）、
 * 也不做权限判断（那是 permissions + 页面的事）。
 * 三者分开，换任何一层都不用动另外两层。
 */

/**
 * 当前登录用户的角色与权限快照。
 *
 * 它是「界面上显不显示管理入口」的唯一依据，因此和后端守卫取的是同一份数据
 * （后端 `GetMyAccessUseCase` 用的就是守卫那个 `get_permission_codes`）。
 *
 * 后端把它单独开成一个端点而不是塞进 `/auth/me`：
 * 用户视图要被注册、登录、改资料三处共用，往里加角色会让 identity 反向依赖 access。
 */
export function fetchMyAccess(): Promise<AccessSummary> {
  return request<AccessSummary>('/auth/me/access')
}

/** 分页拉用户列表。offset / limit 由调用方（翻页按钮）决定。 */
export function fetchUsers(offset: number, limit: number): Promise<UserPage> {
  // 用 URLSearchParams 而不是手拼模板串：手拼遇到将来加筛选参数时很容易忘记 encode
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  return request<UserPage>(`/users?${params.toString()}`)
}

/** 角色目录（含每个角色拥有的权限码）。 */
export function fetchRoles(): Promise<Role[]> {
  return request<Role[]>('/roles')
}

/**
 * 整体**替换**某用户的角色集合。
 *
 * PUT 对应后端的替换语义：传进去的就是最终状态，重复提交不会叠加，
 * 也不会漏删。传空数组表示收回全部角色。
 */
export function assignUserRoles(userId: string, roleCodes: string[]): Promise<Role[]> {
  return request<Role[]>(`/users/${userId}/roles`, {
    method: 'PUT',
    body: { role_codes: roleCodes },
  })
}

/**
 * 管理员重置某用户的密码。
 *
 * 刻意**不**复用 `/auth/change-password`：那个端点的语义是「我改我自己的」，
 * 它从 token 里取用户、并要求带上旧密码。管理员两个前提都不成立
 * （他不是目标用户，目标用户恰恰想不起旧密码）。
 * 后端把它们拆成两个端点、各挂各的守卫，前端这里也必须跟着分开。
 */
export function resetUserPassword(userId: string, newPassword: string): Promise<AuthUser> {
  return request<AuthUser>(`/users/${userId}/password`, {
    method: 'PUT',
    body: { new_password: newPassword },
  })
}

// 用户列表的 queryKey 前缀单独提出来：失效时要按前缀匹配，
// 写成 `['access','users']` 字面量容易和 `users()` 生成器的结构漂移。
const USERS_ROOT = ['access', 'users'] as const

/**
 * queryKey 工厂。
 *
 * 分页键里带上 offset / limit：不同页是不同的缓存条目，翻回上一页立刻命中，
 * 也让「改完角色只失效列表」这件事的表达保持精确（前缀匹配）。
 */
export const accessKeys = {
  myAccess: ['access', 'my-access'] as const,
  roles: ['access', 'roles'] as const,
  usersRoot: USERS_ROOT,
  users: (offset: number, limit: number) => [...USERS_ROOT, offset, limit] as const,
}
