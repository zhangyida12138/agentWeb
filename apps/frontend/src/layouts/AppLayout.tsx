import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useMeQuery } from '../features/auth/hooks'
import { clearAuth, useAuth } from '../stores/auth'

/**
 * 受保护区域的整体布局：顶部导航 + 内容出口。
 *
 * 这里顺带做一次 `/auth/me` 查询，目的有二：
 *   ① 用服务端的最新资料刷新 store（store 里存的是登录那一刻的快照）；
 *   ② 若 token 已失效，请求会 401 → api 层清掉登录态 → RequireAuth 自动把人送回登录页。
 *      「打开页面就发现登录过期」因此不需要任何额外的定时器或校验逻辑。
 */

const NAV_ITEMS = [
  { to: '/', label: '首页', end: true },
  { to: '/profile', label: '个人中心', end: false },
]

export function AppLayout() {
  const auth = useAuth()
  const navigate = useNavigate()

  useMeQuery()

  const handleLogout = () => {
    clearAuth()
    // 用 replace：退出后不该还能靠浏览器「后退」回到受保护页面
    navigate('/login', { replace: true })
  }

  const displayName = auth.user?.display_name || auth.user?.username || '未登录'

  return (
    <div className="min-h-screen">
      <header className="bg-white border-b border-gray-200">
        <div className="mx-auto max-w-4xl px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <span className="font-bold text-gray-900">AgentWeb</span>
            <nav className="flex items-center gap-4">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `text-sm transition-colors ${
                      isActive ? 'text-brand font-medium' : 'text-gray-600 hover:text-gray-900'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {auth.user?.avatar_url ? (
              <img
                src={auth.user.avatar_url}
                alt=""
                className="w-7 h-7 rounded-full object-cover bg-gray-100"
              />
            ) : (
              // 没有头像时用显示名首字符兜底，避免一个灰色问号方块
              <span className="w-7 h-7 rounded-full bg-brand text-white text-xs flex items-center justify-center">
                {displayName.slice(0, 1).toUpperCase()}
              </span>
            )}
            <span className="text-sm text-gray-700 max-w-[10rem] truncate">{displayName}</span>
            <button
              type="button"
              onClick={handleLogout}
              className="text-sm text-gray-500 hover:text-red-600 transition-colors"
            >
              退出
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
