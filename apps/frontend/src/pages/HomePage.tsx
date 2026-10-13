import { Link } from 'react-router-dom'

import { useAuth } from '../stores/auth'

/**
 * 首页占位。
 *
 * P8 会把这里换成文章列表（见 PLAN.md 8.1）。现在只承担两件事：
 * 证明「登录 → 进入受保护区域」这条链路通了，并给个人中心一个入口。
 */
export function HomePage() {
  const { user } = useAuth()

  return (
    <div className="rounded-2xl bg-white border border-gray-100 p-8 shadow-sm">
      <h1 className="text-xl font-semibold text-gray-900">
        欢迎回来，{user?.display_name || user?.username}
      </h1>
      <p className="mt-2 text-sm text-gray-500">文章列表、Agent 对话等功能还在路上。</p>
      <Link
        to="/profile"
        className="mt-6 inline-block rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
      >
        去个人中心
      </Link>
    </div>
  )
}
