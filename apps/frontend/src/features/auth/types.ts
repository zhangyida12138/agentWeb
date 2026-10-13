/**
 * 认证相关的类型。
 *
 * 字段与后端 `presentation/api/v1/schemas/auth.py` 一一对应：
 *    UserResponse   → AuthUser
 *    TokenResponse  → TokenPayload
 *    AuthResponse   → LoginResult
 * 刻意没有 password_hash——后端出参 schema 里就没有这个字段。
 */

/** 后端返回的时间是 ISO 字符串，前端不做转换，展示时交给 formatDateTime。 */
export interface AuthUser {
  id: string
  email: string
  username: string
  display_name: string
  avatar_url: string | null
  bio: string | null
  is_active: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TokenPayload {
  access_token: string
  token_type: string
  /** 剩余有效秒数 */
  expires_in: number
}

export interface LoginResult {
  token: TokenPayload
  user: AuthUser
}

export interface LoginInput {
  email: string
  password: string
}

/**
 * 注册入参。
 *
 * 规则与后端 `RegisterRequest` 对齐（3~32 位字母/数字/下划线/连字符、密码 8~64 字符）。
 * `display_name` 允许 null：留空就用用户名替代显示。
 */
export interface RegisterInput {
  email: string
  username: string
  password: string
  display_name?: string | null
}

/**
 * 注册结果就是用户本身，**没有 token**。
 *
 * 后端刻意不在注册时签发令牌（见 endpoints/auth.py 的 docstring）：
 * 「拿到 token」只有登录一个来源，前端的登录态写入路径就只有一条分支。
 * 所以注册成功后要引导用户去登录页，而不是直接进首页。
 */
export type RegisterResult = AuthUser

/**
 * 改资料入参（PATCH 语义）。
 *
 * 关键点：`undefined` 表示「这个字段本次不改」。
 * 后端用 `exclude_unset=True` 区分「没传」与「传了 null」，
 * 所以构造请求体时必须**只带上真正改过的键**——见 ProfilePage 里的 diff 逻辑。
 * `null` 表示「清空」。
 */
export interface UpdateProfileInput {
  display_name?: string | null
  avatar_url?: string | null
  bio?: string | null
}

export interface ChangePasswordInput {
  old_password: string
  new_password: string
}
