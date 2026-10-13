import type { ReactNode } from 'react'
import { Outlet } from 'react-router-dom'

import { Alert } from './Alert'
import { ApiError } from '../lib/api'
import { useMyAccessQuery } from '../features/access/hooks'
import type { PermissionCode } from '../features/access/permissions'

/**
 * 路由级权限守卫。
 *
 * 与页面内的权限判断是**两层、各有职责**，不是重复劳动：
 *   这一层管「这个 URL 该不该进得去」，页面内那层管「页面里哪些动作能点」。
 *   一个页面往往需要「读」和「写」两种权限，守卫只能按其中最低门槛拦一次，
 *   细粒度的按钮级判断还是得留在页面里。
 *
 * 为什么不做成静默 `Navigate to="/"`：
 *   用户会以为自己点错链接了，反复点几次还是回到首页，问题永远说不清。
 *   把「你缺哪个权限」明说出来，他才知道该找谁开通。
 *
 * 为什么要等权限查询结束才判断：
 *   权限是异步来的。如果默认放行，无权限的用户会先看到页面骨架闪一下
 *   再被替换掉（内容甚至可能已经渲染出来了）；如果默认拒绝，
 *   有权限的用户每次刷新都会先吃一个「无权访问」再跳回来。
 *   两者都很难看，所以宁可等——`isPending` 期间只渲染一行加载文字。
 */
export function RequirePermission({
  permission,
  children,
}: {
  permission: PermissionCode
  /**
   * 不传时渲染 `<Outlet />`。
   *
   * 这样同一个组件既能当「包装器」（`<RequirePermission><Page/></RequirePermission>`），
   * 也能当**无形路由**（`{ element: <RequirePermission/>, children: [...] }`）。
   * 无形路由那个用法更可取：它先于子页面挂载，页面组件根本不会被创建，
   * 于是也就不会触发页面的数据请求——正是拦权限要的效果。
   */
  children?: ReactNode
}) {
  const accessQuery = useMyAccessQuery()

  if (accessQuery.isPending) {
    return <p className="text-sm text-gray-500">加载中…</p>
  }

  if (accessQuery.error) {
    return (
      <Alert tone="error">
        {accessQuery.error instanceof ApiError
          ? accessQuery.error.message
          : '无法读取当前用户的权限，请稍后重试'}
      </Alert>
    )
  }

  if (!accessQuery.data?.permission_codes.includes(permission)) {
    return (
      <Alert tone="error">你没有访问该页面所需的权限（{permission}）。请联系管理员为你分配。</Alert>
    )
  }

  return <>{children ?? <Outlet />}</>
}
