import { formatDateTime } from '@agent-web/shared'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { ApiError } from '../../lib/api'
import { useMeQuery } from '../auth/hooks'

import { ProfileForm } from './ProfileForm'

/**
 * 个人中心：只读账户信息 + 可编辑的基本资料，另给「修改密码」一个入口。
 *
 * 改密为什么独立成页而不是嵌在这里的第三块表单：
 *   它的校验规则（要验旧密码）、失败原因（401 + 40110）、成功后的影响
 *   （会不会踢掉其他设备）都和改资料完全不同，混在一页里用户会分不清
 *   「刚才是哪一项失败了」。独立页面还能被守卫单独保护起来。
 */

function Card({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-2xl bg-white border border-gray-100 p-6 shadow-sm">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {description && <p className="mt-1 mb-4 text-xs text-gray-500">{description}</p>}
      {!description && <div className="mb-4" />}
      {children}
    </section>
  )
}

export function ProfilePage() {
  const { data: user, isPending, error } = useMeQuery()

  if (isPending) {
    return <p className="text-sm text-gray-500">加载中…</p>
  }

  if (error || !user) {
    // token 失效时 api 层已经清掉登录态，RequireAuth 会接管跳转；
    // 这里只负责展示「其余失败原因」，不给用户一个空白页。
    const message = error instanceof ApiError ? error.message : '无法加载用户信息'
    return <Alert tone="error">{message}</Alert>
  }

  return (
    <div className="flex flex-col gap-6">
      <Card title="账户信息" description="以下信息不可自行修改">
        <dl className="grid grid-cols-[6rem_1fr] gap-y-2 text-sm">
          <dt className="text-gray-500">邮箱</dt>
          <dd className="text-gray-900 break-all">{user.email}</dd>
          <dt className="text-gray-500">用户名</dt>
          <dd className="text-gray-900">{user.username}</dd>
          <dt className="text-gray-500">注册时间</dt>
          <dd className="text-gray-900">{formatDateTime(user.created_at)}</dd>
          <dt className="text-gray-500">状态</dt>
          <dd className={user.is_active ? 'text-green-600' : 'text-red-600'}>
            {user.is_active ? '正常' : '已停用'}
          </dd>
        </dl>
      </Card>

      <Card title="基本资料" description="只提交改动过的字段，未修改的内容不会被覆盖">
        {/* key 绑定用户 id：切换账号时强制重建表单内部状态，
            否则会带着上一个账号的输入继续编辑（store 里还有缓存时容易出现） */}
        <ProfileForm key={user.id} user={user} />
      </Card>

      <Card title="密码与安全" description="修改密码需要验证当前密码">
        <Link
          to="/change-password"
          className="inline-block rounded-lg border border-brand px-4 py-2 text-sm font-medium text-brand transition-colors hover:bg-purple-50"
        >
          修改密码 →
        </Link>
      </Card>
    </div>
  )
}
