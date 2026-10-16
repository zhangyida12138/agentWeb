import type { ChangeEvent, ReactNode } from 'react'

/**
 * 表单字段外壳：label + 控件 + 错误/提示文案。
 *
 * 抽出来的理由：登录页和资料页一共 7 个输入框，每个都要重复
 * 「label 关联、错误红色文案、字数计数」这一套。重复到第 3 遍就该抽了。
 * 这里只做展示，不持有状态——受控组件由调用方管。
 */

interface FieldShellProps {
  id: string
  label: string
  error?: string
  hint?: ReactNode
  /** 右下角的字数计数，如 "12/64" */
  counter?: string
  children: ReactNode
}

function FieldShell({ id, label, error, hint, counter, children }: FieldShellProps) {
  return (
    <div className="mb-4">
      <div className="mb-1 flex items-baseline justify-between">
        <label htmlFor={id} className="text-sm font-medium text-gray-700">
          {label}
        </label>
        {counter && <span className="text-xs text-gray-400">{counter}</span>}
      </div>

      {children}

      {/* 错误优先于提示：两者同时存在时，用户更需要先看到错误 */}
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-red-600">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>
      )}
    </div>
  )
}

const CONTROL_CLASS = [
  'w-full px-3 py-2 rounded-lg border bg-white text-sm',
  'transition-colors outline-none',
  'disabled:bg-gray-100 disabled:text-gray-500',
].join(' ')

interface TextFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'email' | 'password' | 'url'
  placeholder?: string
  autoComplete?: string
  maxLength?: number
  required?: boolean
  disabled?: boolean
  error?: string
  hint?: ReactNode
  /** 输入时是否原样保留（密码框不需要 trim） */
  trim?: boolean
  /**
   * 挂载后自动聚焦。
   *
   * 存在的理由不是"体验更好"，而是 `Modal` 明确把焦点这件事交给了调用方：
   * 它没有实现焦点陷阱（代码量比弹窗本身还大），只留了 `autoFocus` 这一个出口。
   * 没有这个属性的话，弹窗里唯一能自动聚焦的元素就只有 `<select>`——
   * 于是"新建标签"会默认聚焦在类型上而不是名字上，用户打开弹窗后
   * 打出来的字会跑进错误的地方。
   */
  autoFocus?: boolean
}

export function TextField({
  id,
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  autoComplete,
  maxLength,
  required,
  disabled,
  error,
  hint,
  trim = true,
  autoFocus,
}: TextFieldProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.value
    // 只去掉首尾空格：邮箱和用户名带空格是纯粹的输入失误，
    // 但中间的空格可能是密码的一部分，所以密码框传 trim={false}
    onChange(trim ? next.trim() : next)
  }

  return (
    <FieldShell
      id={id}
      label={label}
      error={error}
      hint={hint}
      counter={maxLength ? `${value.length}/${maxLength}` : undefined}
    >
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        onChange={handleChange}
        placeholder={placeholder}
        autoComplete={autoComplete}
        maxLength={maxLength}
        required={required}
        disabled={disabled}
        autoFocus={autoFocus}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`${CONTROL_CLASS} ${
          error ? 'border-red-400 focus:border-red-500' : 'border-gray-300 focus:border-brand'
        } focus:ring-2 ${error ? 'focus:ring-red-100' : 'focus:ring-purple-100'}`}
      />
    </FieldShell>
  )
}

interface TextAreaFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  maxLength?: number
  placeholder?: string
  disabled?: boolean
  error?: string
  hint?: ReactNode
}

export function TextAreaField({
  id,
  label,
  value,
  onChange,
  rows = 4,
  maxLength,
  placeholder,
  disabled,
  error,
  hint,
}: TextAreaFieldProps) {
  return (
    <FieldShell
      id={id}
      label={label}
      error={error}
      hint={hint}
      counter={maxLength ? `${value.length}/${maxLength}` : undefined}
    >
      <textarea
        id={id}
        name={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        maxLength={maxLength}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`${CONTROL_CLASS} resize-y ${
          error ? 'border-red-400 focus:border-red-500' : 'border-gray-300 focus:border-brand'
        } focus:ring-2 ${error ? 'focus:ring-red-100' : 'focus:ring-purple-100'}`}
      />
    </FieldShell>
  )
}
