import type { ReactNode } from 'react'

/**
 * 登录 / 注册这类「未进入应用」的页面外壳：居中卡片 + 品牌 + 副标题 + 底部链接。
 *
 * 抽出来的理由和 Field.tsx 一样——重复到第二遍就该抽了：两个页面除了表单本身，
 * 外层结构一字不差。留着两份复制粘贴，改一处忘一处只是时间问题。
 */

interface AuthShellProps {
  /** 品牌名固定，页面之间的差别只在副标题里，所以只开放 subtitle */
  subtitle: string
  children: ReactNode
  /** 卡片下方的次要链接区，如「还没有账号？去注册」 */
  footer?: ReactNode
}

export function AuthShell({ subtitle, children, footer }: AuthShellProps) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-gray-900">AgentWeb</h1>
          <p className="mt-2 text-sm text-gray-500">{subtitle}</p>
        </div>

        <div className="rounded-2xl bg-white p-6 shadow-sm border border-gray-100">{children}</div>

        {footer && <div className="mt-4 text-center text-xs text-gray-500">{footer}</div>}
      </div>
    </div>
  )
}
