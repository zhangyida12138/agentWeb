import { Link } from 'react-router-dom'

import { ChangePasswordForm } from './ChangePasswordForm'

/**
 * 修改密码页。
 *
 * **暂时只允许登录后进行**：路由挂在 RequireAuth 之下，未登录访问会被守卫
 * 重定向到登录页（并带上 from，登录后自动回到这里）。
 *
 * 之所以不做「忘记密码」那条公开路径，是因为它需要邮箱验证码 / 重置链接这一整套
 * 邮件基础设施，当前后端没有对应能力（见 PLAN.md 的待办）。先只做「记得旧密码」的场景。
 */

export function ChangePasswordPage() {
  return (
    <div className="mx-auto max-w-lg">
      <div className="rounded-2xl bg-white border border-gray-100 p-6 shadow-sm">
        <h1 className="text-base font-semibold text-gray-900">修改密码</h1>
        <p className="mt-1 mb-4 text-xs text-gray-500">
          需要验证当前密码。改密不会让已签发的令牌立即失效，其他设备的登录状态会在令牌过期后结束。
        </p>

        <ChangePasswordForm />
      </div>

      <p className="mt-4 text-xs">
        <Link to="/profile" className="text-brand hover:underline">
          ← 返回个人中心
        </Link>
      </p>
    </div>
  )
}
