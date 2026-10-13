import { useSyncExternalStore } from 'react'

import type { AuthUser, TokenPayload } from '../features/auth/types'

/**
 * 登录态（token + 当前用户）。
 *
 * 为什么不用 zustand：本仓库现有依赖里没有它，而这里需要的全部能力
 * （读、写、订阅、跨标签页同步）用 `useSyncExternalStore` + localStorage 就够了。
 * 少一个依赖，也少一层「框架怎么实现」的理解成本。
 *
 * 为什么状态要放在 React 之外：
 *     `lib/api.ts` 需要在**非组件**环境里读 token（注入 Authorization 头）、
 *     在 401 时清登录态。如果状态只活在 Context 里，api 层就拿不到它。
 */

const STORAGE_KEY = 'agent-web.auth'

export interface AuthState {
  token: string | null
  /** token 过期时间戳（毫秒）。null 表示未知，此时不做本地过期判断。 */
  expiresAt: number | null
  user: AuthUser | null
}

const EMPTY_STATE: AuthState = { token: null, expiresAt: null, user: null }

function readFromStorage(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return EMPTY_STATE

    const parsed = JSON.parse(raw) as Partial<AuthState>
    if (typeof parsed.token !== 'string' || !parsed.token) return EMPTY_STATE

    // 本地过期判断只是「少一次必然失败的请求」，不是安全边界：
    // 真正的有效性由后端验签决定，所以这里判断错了也不会造成越权。
    if (typeof parsed.expiresAt === 'number' && parsed.expiresAt <= Date.now()) {
      localStorage.removeItem(STORAGE_KEY)
      return EMPTY_STATE
    }

    return {
      token: parsed.token,
      expiresAt: typeof parsed.expiresAt === 'number' ? parsed.expiresAt : null,
      user: parsed.user ?? null,
    }
  } catch {
    // 存储被写坏（手动改过、旧版本结构）时按未登录处理，而不是让整个应用白屏
    return EMPTY_STATE
  }
}

let state: AuthState = readFromStorage()
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

function commit(next: AuthState): void {
  state = next
  try {
    if (next.token) localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 隐私模式下 localStorage 可能不可写。此时降级为「仅内存登录态」，
    // 刷新页面需要重新登录，但功能本身不受影响。
  }
  emit()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 跨标签页同步：另一个标签页登录/退出后，本页跟着更新。 */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY) return
    state = readFromStorage()
    emit()
  })
}

// ──────────────────────────── 对外读写 ────────────────────────────

export function getToken(): string | null {
  return state.token
}

export function getAuthState(): AuthState {
  return state
}

/** 登录成功后写入。`expires_in` 是后端给的剩余秒数，换算成绝对时间戳存储。 */
export function setAuth(payload: TokenPayload, user: AuthUser): void {
  commit({
    token: payload.access_token,
    expiresAt: payload.expires_in ? Date.now() + payload.expires_in * 1000 : null,
    user,
  })
}

/** 只刷新用户信息（改资料后用），不动 token。 */
export function setUser(user: AuthUser): void {
  if (!state.token) return
  commit({ ...state, user })
}

export function clearAuth(): void {
  if (state.token === null && state.user === null) return
  commit(EMPTY_STATE)
}

/**
 * 订阅登录态变化。
 *
 * 为什么需要它：登录态变化意味着「换人了」，而 React Query 的缓存是**模块级单例**，
 * 生命周期比一次会话长得多。不主动作废的话，下一个登录者会直接命中
 * 上一个身份的 fresh 缓存（权限快照、个人资料都会串）。
 *
 * 为什么做成订阅而不是在调用点手动清缓存：会改动 token 的地方有四处
 * ——登录、主动退出、401 自动登出、跨标签页同步——
 * 逐一记得补一句清理，是一次注定会漏的约定；订阅把这件事变成结构上的必然。
 */
export function subscribeAuth(listener: () => void): () => void {
  return subscribe(listener)
}

/** 组件里读登录态。字段引用稳定，不会触发无意义的重复渲染。 */
export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, getAuthState, getAuthState)
}
