import { createBrowserRouter, Navigate } from 'react-router-dom'

import { RequireAuth } from './components/RequireAuth'
import { RequirePermission } from './components/RequirePermission'
import { UserManagementPage } from './features/access/UserManagementPage'
import { PERMISSION } from './features/access/permissions'
import { ChangePasswordPage } from './features/auth/ChangePasswordPage'
import { LoginPage } from './features/auth/LoginPage'
import { RegisterPage } from './features/auth/RegisterPage'
import { ProfilePage } from './features/profile/ProfilePage'
import { AppLayout } from './layouts/AppLayout'
import { HomePage } from './pages/HomePage'

/**
 * 路由表。
 *
 * 结构上分三层，顺序即语义：
 *   公开区（/login、/register）
 *   → 守卫层（RequireAuth，只判断登录态；RequirePermission，再判权限）
 *   → 布局层（AppLayout，页头 + Outlet）
 *
 * `/change-password` 放在守卫层**内部**：改密必须先登录（后端接口本身也要求
 * 当前用户，未登录访问只会拿到 401）。没有「忘记密码」那条公开路径，
 * 因为那需要邮件验证码一整套基础设施。
 *
 * `/admin/users` 用 **pathless 路由**把 RequirePermission 套在 path 上：
 *   守卫要先于页面挂载，才能在页面发请求之前就拦住。
 *   写成 `element: <RequirePermission><UserManagementPage/></RequirePermission>`
 *   也能跑，但那样页面元素会被立即创建（React 只是不用它），
 *   无权限的人依旧会触发页面的数据请求——正是我们想避免的。
 */
export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/register',
    element: <RegisterPage />,
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          // index 路由不写 path：`/` 由父级的空 path 继承而来，
          // 同时写 index 和 path 会被 react-router 判为非法配置
          { index: true, element: <HomePage /> },
          { path: 'profile', element: <ProfilePage /> },
          { path: 'change-password', element: <ChangePasswordPage /> },
          {
            element: <RequirePermission permission={PERMISSION.USER_LIST} />,
            children: [{ path: 'admin/users', element: <UserManagementPage /> }],
          },
        ],
      },
    ],
  },
  {
    // 兜底：未知路径统一回首页。
    // 受保护区域之外的地址会先被守卫拦到登录页，这是期望行为。
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
