import { createBrowserRouter, Navigate } from 'react-router-dom'

import { RequireAuth } from './components/RequireAuth'
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
 *   → 守卫层（RequireAuth，只判断登录态）
 *   → 布局层（AppLayout，页头 + Outlet）
 * 将来 P3 加权限时，只需在守卫层里再叠一个 require_permission 包装，
 * 不用碰任何页面组件。
 *
 * `/change-password` 放在守卫层**内部**：改密必须先登录（后端接口本身也要求
 * 当前用户，未登录访问只会拿到 401）。没有「忘记密码」那条公开路径，
 * 因为那需要邮件验证码一整套基础设施。
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
