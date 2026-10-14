import { formatDateTime } from '@agent-web/shared'
import { useMemo, useState } from 'react'

import { Alert } from '../../components/Alert'
import { ApiError } from '../../lib/api'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery, useRolesQuery, useUsersQuery } from './hooks'
import { PERMISSION, hasPermission } from './permissions'
import { ResetPasswordDialog } from './ResetPasswordDialog'
import { RoleEditDialog } from './RoleEditDialog'
import type { UserWithRoles } from './types'

/**
 * 用户管理页：列出用户、查看角色、编辑角色、重置密码。
 *
 * 权限分层（三层都必要，缺一层都会出现「能看见但点不动」的困惑）：
 *   ① 进不来的情况：页头导航里根本不显示入口（SiteHeader 按权限渲染）；
 *   ② 直接敲 URL 进来：这里显式提示「缺少 user:list」，而不是干瘪的 403；
 *   ③ 单个动作：只显示当前用户真有权用的按钮（有 user:list 但没有
 *      user:assign_roles 的人应该只读，而不是看到几个点了就报错的按钮）。
 *
 * 为什么不做成「无权限就 redirect 回首页」：
 *   静默跳走会让用户以为自己点错了，而实际上他缺的是权限。
 *   把原因说出来，他才知道该去找谁开通。
 */

const PAGE_SIZE = 20

/**
 * 角色徽章的配色。
 *
 * 按**角色编码**查而不是按显示名：编码是稳定的标识符，
 * 而显示名可以在后台改（「作者」→「内容创作者」），
 * 用显示名当 key 时，改名会让所有徽章颜色一起掉回默认灰。
 */
const ROLE_BADGE_CLASS: Record<string, string> = {
  admin: 'bg-purple-50 text-purple-700 border-purple-200',
  author: 'bg-blue-50 text-blue-700 border-blue-200',
  reader: 'bg-gray-50 text-gray-600 border-gray-200',
}
const DEFAULT_BADGE_CLASS = 'bg-gray-50 text-gray-600 border-gray-200'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function UserManagementPage() {
  const { user: currentUser } = useAuth()

  // 页码而不是 offset 作为 state：offset 是派生值，
  // 存 offset 的话每次翻页都要自己算，且两处状态可能不一致
  const [page, setPage] = useState(0)
  const offset = page * PAGE_SIZE

  const accessQuery = useMyAccessQuery()

  // 先算权限再发起列表请求：没有 user:list 的人不该看到一次必然 403 的请求
  //（hook 调用顺序在每次渲染里都一样，先算后调不违反 hooks 规则）
  const permissionCodes = accessQuery.data?.permission_codes
  const canListUsers = hasPermission(permissionCodes, PERMISSION.USER_LIST)
  const canAssignRoles = hasPermission(permissionCodes, PERMISSION.USER_ASSIGN_ROLES)
  const canResetPassword = hasPermission(permissionCodes, PERMISSION.USER_RESET_PASSWORD)

  const rolesQuery = useRolesQuery({ enabled: canListUsers })
  const usersQuery = useUsersQuery(offset, PAGE_SIZE, { enabled: canListUsers })

  const [roleTarget, setRoleTarget] = useState<UserWithRoles | null>(null)
  const [passwordTarget, setPasswordTarget] = useState<UserWithRoles | null>(null)

  /**
   * 角色码 → 显示名，来自角色目录。
   *
   * 不在这里硬编码「admin=管理员」：显示名是数据，后台可能改。
   * 目录还没加载出来时回退显示编码本身——「显示得不够好看」
   * 远好过「显示成空白，让人以为这个用户没有角色」。
   */
  const roleNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const role of rolesQuery.data ?? []) map.set(role.code, role.name)
    return map
  }, [rolesQuery.data])

  if (accessQuery.isPending) {
    return <p className="text-sm text-gray-500">加载中…</p>
  }

  if (accessQuery.error) {
    return <Alert tone="error">{errorMessage(accessQuery.error, '无法读取当前用户的权限')}</Alert>
  }

  if (!canListUsers) {
    return (
      <Alert tone="error">
        你没有「查看用户列表」（{PERMISSION.USER_LIST}
        ）的权限，无法访问用户管理。请联系管理员为你分配。
      </Alert>
    )
  }

  const users = usersQuery.data?.items ?? []
  // 用响应里回传的 limit 而不是本地常量：服务端会把越界值收敛，
  // 拿本地值算总页数会和服务端的实际分页不一致
  const pageSize = usersQuery.data?.limit ?? PAGE_SIZE
  const total = usersQuery.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  // 用「本页起点 + 本页实际条数」而不是 total 判断，避免 total 变化时的边界闪烁
  const hasNextPage = usersQuery.data
    ? usersQuery.data.offset + users.length < usersQuery.data.total
    : false

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">用户管理</h1>
          <p className="mt-1 text-xs text-gray-500">共 {total} 位用户</p>
        </div>
        {usersQuery.isFetching && <span className="text-xs text-gray-400">刷新中…</span>}
      </div>

      {/*
        列表请求失败单独提示，而不是把整页替换成错误：
        权限已经通过（上面那道判断），失败更可能是网络或服务端问题，
        此时保留页面框架、让用户能点「重试」比整页白屏体验好。
      */}
      {usersQuery.error && (
        <Alert tone="error">
          {errorMessage(usersQuery.error, '无法加载用户列表')}
          <button
            type="button"
            onClick={() => void usersQuery.refetch()}
            className="ml-2 underline"
          >
            重试
          </button>
        </Alert>
      )}

      {/*
        表格窄屏下要横向滚动（列比视口宽），而横滑条压在圆角边框下方会显得很脏，
        所以用 `no-scrollbar` 把条藏掉——横滑能力本身还在（触控板双指、Shift+滚轮、
        键盘方向键）。这个容器只在「列确实超出」时才真的滚动，
        正常宽度下它连滚动区域都不是，藏不藏都一样。
      */}
      <div className="overflow-x-auto no-scrollbar rounded-2xl border border-gray-100 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">
                用户
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                角色
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                状态
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                注册时间
              </th>
              <th scope="col" className="px-4 py-3 text-right font-medium">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {usersQuery.isPending && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                  加载中…
                </td>
              </tr>
            )}

            {!usersQuery.isPending && users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                  还没有用户
                </td>
              </tr>
            )}

            {users.map((item) => (
              <tr key={item.user.id} className="align-top">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">
                    {item.user.display_name || item.user.username}
                    {item.user.id === currentUser?.id && (
                      <span className="ml-2 text-xs text-gray-400">（你）</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 break-all">{item.user.email}</div>
                </td>

                <td className="px-4 py-3">
                  {item.role_codes.length === 0 ? (
                    // 「无角色」要明确写出来，不能留空：
                    // 空白会让人误以为「还没加载完」，而它其实是一个需要处理的状态
                    <span className="text-xs text-gray-400">无角色</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {item.role_codes.map((code) => (
                        <span
                          key={code}
                          className={`rounded-full border px-2 py-0.5 text-xs ${
                            ROLE_BADGE_CLASS[code] ?? DEFAULT_BADGE_CLASS
                          }`}
                        >
                          {roleNames.get(code) ?? code}
                        </span>
                      ))}
                    </div>
                  )}
                </td>

                <td className="px-4 py-3">
                  <span className={item.user.is_active ? 'text-green-600' : 'text-red-600'}>
                    {item.user.is_active ? '正常' : '已停用'}
                  </span>
                </td>

                <td className="px-4 py-3 text-xs text-gray-500">
                  {formatDateTime(item.user.created_at)}
                </td>

                <td className="px-4 py-3">
                  <div className="flex justify-end gap-3">
                    {canAssignRoles && (
                      <button
                        type="button"
                        onClick={() => setRoleTarget(item)}
                        className="text-brand transition-opacity hover:opacity-70"
                      >
                        编辑角色
                      </button>
                    )}
                    {canResetPassword && (
                      <button
                        type="button"
                        onClick={() => setPasswordTarget(item)}
                        className="text-brand transition-opacity hover:opacity-70"
                      >
                        重置密码
                      </button>
                    )}
                    {!canAssignRoles && !canResetPassword && (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-end gap-3 text-sm">
          <span className="text-gray-500">
            第 {page + 1} / {pageCount} 页
          </span>
          <button
            type="button"
            onClick={() => setPage((current) => Math.max(0, current - 1))}
            disabled={page === 0 || usersQuery.isFetching}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-40"
          >
            上一页
          </button>
          <button
            type="button"
            onClick={() => setPage((current) => current + 1)}
            disabled={!hasNextPage || usersQuery.isFetching}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-40"
          >
            下一页
          </button>
        </div>
      )}

      {roleTarget && (
        // key 绑定用户 id：换一个用户时强制重建弹窗内部状态，
        // 否则勾选态会带着上一个用户的选择延续下来（看着像「他的角色乱了」）
        <RoleEditDialog
          key={roleTarget.user.id}
          target={roleTarget}
          onClose={() => setRoleTarget(null)}
        />
      )}

      {passwordTarget && (
        <ResetPasswordDialog
          key={passwordTarget.user.id}
          target={passwordTarget}
          isSelf={passwordTarget.user.id === currentUser?.id}
          onClose={() => setPasswordTarget(null)}
        />
      )}
    </div>
  )
}
