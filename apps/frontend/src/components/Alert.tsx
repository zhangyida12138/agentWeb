import type { ReactNode } from 'react'

/**
 * 提示条：用于「整表错误」与「操作成功」两类反馈。
 *
 * `role="alert"` 让屏幕阅读器在内容出现时立刻播报——错误提示是异步出现的，
 * 没有这个属性时视障用户不会知道表单提交失败了。
 */

const TONES = {
  error: {
    wrap: 'bg-red-50 border-red-200 text-red-700',
    icon: '!',
  },
  success: {
    wrap: 'bg-green-50 border-green-200 text-green-700',
    icon: '✓',
  },
  info: {
    wrap: 'bg-purple-50 border-purple-200 text-purple-700',
    icon: 'i',
  },
} as const

interface AlertProps {
  tone?: keyof typeof TONES
  children: ReactNode
}

export function Alert({ tone = 'error', children }: AlertProps) {
  const style = TONES[tone]
  return (
    <div
      role="alert"
      className={`mb-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${style.wrap}`}
    >
      <span aria-hidden="true" className="mt-px font-bold">
        {style.icon}
      </span>
      <div className="flex-1">{children}</div>
    </div>
  )
}
