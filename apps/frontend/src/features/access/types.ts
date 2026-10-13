import type { AuthUser } from '../auth/types'

/**
 * access（用户与权限管理）相关的响应类型。
 *
 * 这些形状和后端 `app/presentation/api/v1/schemas/access.py` 是**契约**关系：
 * 后端改了字段名，这里必须一起改，否则运行时才会发现（`data.items` 变成 undefined）。
 */

/** 角色出参（`GET /api/v1/roles` 的单项）。 */
export interface Role {
  id: string
  code: string
  name: string
  description: string | null
  /** 该角色拥有的权限码。目前界面上不用，但它是「权限矩阵」的另一根坐标轴，先留着 */
  permission_codes: string[]
}

/**
 * 用户列表项：用户视图 + 他的角色码。
 *
 * 复用 `AuthUser` 而不是另立一套用户字段：
 *   管理页里显示的人和「个人中心」里显示的人必须是同一个形状，
 *   否则同一个人在两处会有两套解析逻辑，改一处漏一处是迟早的事。
 */
export interface UserWithRoles {
  user: AuthUser
  role_codes: string[]
}

/**
 * 用户分页。
 *
 * `offset` / `limit` 是**服务端收敛后**的实际值，不是请求里传的那份：
 * 传 limit=1000 会拿回 limit=100，用自己传的值算总页数一定会算错。
 * `total` 是全量条数（不只是本页）。
 */
export interface UserPage {
  items: UserWithRoles[]
  total: number
  offset: number
  limit: number
}

/** 当前登录用户的角色与权限（`GET /api/v1/auth/me/access`）。 */
export interface AccessSummary {
  role_codes: string[]
  permission_codes: string[]
}
