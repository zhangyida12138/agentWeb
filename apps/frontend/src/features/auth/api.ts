import { request } from '../../lib/api'

import type {
  AuthUser,
  ChangePasswordInput,
  LoginInput,
  LoginResult,
  RegisterInput,
  RegisterResult,
  UpdateProfileInput,
} from './types'

/**
 * 认证接口的唯一入口。
 *
 * 组件里不直接写 fetch 字符串：路径、方法、请求体形状集中在这里，
 * 后端改路径时只改这一个文件。
 */

export function login(input: LoginInput): Promise<LoginResult> {
  return request<LoginResult>('/auth/login', { method: 'POST', body: input })
}

/**
 * 注册。
 *
 * 后端返回 201 + UserResponse，**不带 token**，所以调用方拿到的是一个普通用户对象，
 * 不能像 login 那样直接 `setAuth`——注册完必须再去登录一次。
 */
export function register(input: RegisterInput): Promise<RegisterResult> {
  return request<RegisterResult>('/auth/register', { method: 'POST', body: input })
}

export function fetchMe(): Promise<AuthUser> {
  return request<AuthUser>('/auth/me')
}

export function updateProfile(input: UpdateProfileInput): Promise<AuthUser> {
  return request<AuthUser>('/auth/me', { method: 'PATCH', body: input })
}

/** 后端返回的是 `{code,data:null,message:'密码修改成功'}`，没有需要用的数据。 */
export function changePassword(input: ChangePasswordInput): Promise<null> {
  return request<null>('/auth/change-password', { method: 'POST', body: input })
}

/** Query key 集中定义：避免各处手写字符串导致缓存对不上。 */
export const authKeys = {
  me: ['auth', 'me'] as const,
}
