import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { setUser } from '../../stores/auth'

import { authKeys, changePassword, fetchMe, register, updateProfile } from './api'

import type { AuthUser, ChangePasswordInput, RegisterInput, UpdateProfileInput } from './types'

/**
 * `/auth/me` 的查询。
 *
 * 页头与资料页共用同一个 key，TanStack Query 会去重成**一次**请求；
 * 数据命中后顺带把 store 里的用户同步一遍——页头、头像这类地方读的是 store，
 * 而 store 里的副本可能还是登录那一刻的快照（display_name 早被改过）。
 *
 * 同步放在 effect 里而不是 `select`：`select` 必须是纯函数，
 * 在里面写 store 会让「查询」隐式产生副作用，重渲染次数一多就会打架。
 */
export function useMeQuery(options: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: authKeys.me,
    queryFn: fetchMe,
    enabled: options.enabled ?? true,
  })

  const user = query.data
  useEffect(() => {
    if (user) setUser(user)
  }, [user])

  return query
}

/** 改资料。成功后把结果直接写进缓存并同步 store，省掉一次多余的回查。 */
export function useUpdateProfileMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: UpdateProfileInput) => updateProfile(input),
    onSuccess: (user: AuthUser) => {
      queryClient.setQueryData(authKeys.me, user)
      setUser(user)
    },
  })
}

/**
 * 注册。
 *
 * 刻意**不做**任何缓存写入或登录态变更：注册接口不返回 token，
 * 这里唯一能做的就是让调用方拿到新用户对象（用于提示「xxx 已创建」），
 * 真正的登录由用户在登录页显式完成。
 */
export function useRegisterMutation() {
  return useMutation({
    mutationFn: (input: RegisterInput) => register(input),
  })
}

export function useChangePasswordMutation() {
  return useMutation({
    mutationFn: (input: ChangePasswordInput) => changePassword(input),
  })
}
