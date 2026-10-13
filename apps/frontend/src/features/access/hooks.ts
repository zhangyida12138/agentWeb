import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  accessKeys,
  assignUserRoles,
  fetchMyAccess,
  fetchRoles,
  fetchUsers,
  resetUserPassword,
} from './api'

/**
 * access 模块的数据钩子。
 *
 * 缓存策略集中在这里，页面只读 `data` / `isPending` / `error`：
 *   权限和角色目录用长 staleTime（5 分钟）——它们不是需要秒级感知的数据，
 *   而页头和页面都要用同一份，缓存能避免每次导航都打接口；
 *   用户列表用 `keepPreviousData`——翻页时保留上一页内容，
 *   表格不会在切页瞬间塌成空白再长出来。
 */

export function useMyAccessQuery() {
  return useQuery({
    queryKey: accessKeys.myAccess,
    queryFn: fetchMyAccess,
    staleTime: 5 * 60 * 1000,
  })
}

export function useRolesQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: accessKeys.roles,
    queryFn: fetchRoles,
    staleTime: 5 * 60 * 1000,
    enabled: options.enabled ?? true,
  })
}

/**
 * 分页用户列表。
 *
 * `enabled` 用来表达「没有 user:list 权限就别请求」：
 *   后端会用 403 拒掉这次请求，而前端已经知道会拿到 403
 *   （权限快照就在手上），那就不该把一次必然失败的请求发出去。
 */
export function useUsersQuery(offset: number, limit: number, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: accessKeys.users(offset, limit),
    queryFn: () => fetchUsers(offset, limit),
    // 翻页时先显示上一页的数据（配一个轻微的 loading 态），避免整块表格闪烁
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  })
}

/**
 * 替换某用户的角色。
 *
 * 成功后失效两样东西，各有理由：
 *   ① 用户列表：角色徽章是列表的一部分，不刷新就还是旧的那排标签；
 *   ② **自己的权限快照**：管理员完全可能改的就是自己（把 admin 摘掉），
 *      而此时页头的「用户管理」入口还挂在 5 分钟 staleTime 内不变，
 *      看起来就像「摘了 admin 还是管理员」。
 * 为什么不管改的是谁都失效②：前端无法察觉「别再处管理员改了我的角色」，
 * 而多一次 GET 的代价远小于「权限显示与实际不符」这件事的代价。
 */
export function useAssignRolesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, roleCodes }: { userId: string; roleCodes: string[] }) =>
      assignUserRoles(userId, roleCodes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: accessKeys.usersRoot })
      void queryClient.invalidateQueries({ queryKey: accessKeys.myAccess })
    },
  })
}

/**
 * 重置某用户的密码。
 *
 * 成功后同样刷新列表：密码变了、`updated_at` 也就变了，
 * 不刷新的话表格里那一行会停留在旧时间，看起来像没生效。
 */
export function useResetUserPasswordMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, newPassword }: { userId: string; newPassword: string }) =>
      resetUserPassword(userId, newPassword),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: accessKeys.usersRoot }),
  })
}
