import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { TextField } from '../../components/Field'
import { ApiError } from '../../lib/api'
import { withoutFieldError, withFieldError } from '../../lib/form'

import { AuthShell } from './AuthShell'
import { useRegisterMutation } from './hooks'

/**
 * 注册页。
 *
 * 两个和后端约定强相关的点：
 *
 *   ① **注册成功 ≠ 已登录**。`POST /auth/register` 返回 201 + 用户对象，不带 token
 *      （后端有意为之：签发令牌只有登录一个来源）。所以这里成功后跳登录页并把邮箱带过去，
 *      而不是自作主张再打一次登录接口——那会让「token 从哪来」多出一条隐含分支。
 *
 *   ② 本地校验与后端 schema **逐条对齐**（用户名 3~32 位字母/数字/下划线/连字符、
 *      密码 8~64 字符）。前端做这些不是为了安全，而是为了「不用等一个来回才知道写错」；
 *      真正的边界仍由后端 schema + 值对象把守，所以这里不实现任何后端没有的规则。
 */

interface FormValues {
  email: string
  username: string
  password: string
  confirm_password: string
  display_name: string
}

const EMPTY_FORM: FormValues = {
  email: '',
  username: '',
  password: '',
  confirm_password: '',
  display_name: '',
}

// 与 presentation/api/v1/schemas/auth.py 中的常量保持一致
const USERNAME_MIN_LEN = 3
const USERNAME_MAX_LEN = 32
const PASSWORD_MIN_LEN = 8
const PASSWORD_MAX_LEN = 64
const DISPLAY_NAME_MAX_LEN = 64
/** 与 schema 的 pattern=r"^[A-Za-z0-9_-]+$" 等价 */
const USERNAME_PATTERN = /^[A-Za-z0-9_-]+$/
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

type Errors = Partial<Record<keyof FormValues, string>>

function validate(values: FormValues): Errors {
  const errors: Errors = {}

  if (!values.email) errors.email = '请输入邮箱'
  else if (!EMAIL_PATTERN.test(values.email)) errors.email = '邮箱格式不正确'

  if (!values.username) errors.username = '请输入用户名'
  else if (values.username.length < USERNAME_MIN_LEN) {
    errors.username = `用户名至少 ${USERNAME_MIN_LEN} 个字符`
  } else if (values.username.length > USERNAME_MAX_LEN) {
    errors.username = `用户名最多 ${USERNAME_MAX_LEN} 个字符`
  } else if (!USERNAME_PATTERN.test(values.username)) {
    errors.username = '用户名只能包含字母、数字、下划线或连字符'
  }

  if (!values.password) errors.password = '请输入密码'
  else if (values.password.length < PASSWORD_MIN_LEN) {
    errors.password = `密码至少 ${PASSWORD_MIN_LEN} 个字符`
  } else if (values.password.length > PASSWORD_MAX_LEN) {
    errors.password = `密码最多 ${PASSWORD_MAX_LEN} 个字符`
  }

  if (!values.confirm_password) errors.confirm_password = '请再次输入密码'
  else if (values.confirm_password !== values.password) {
    errors.confirm_password = '两次输入的密码不一致'
  }

  // maxLength 已经挡住了超长输入，这里只是「万一被绕过」的兜底
  if (values.display_name.length > DISPLAY_NAME_MAX_LEN) {
    errors.display_name = `显示名最多 ${DISPLAY_NAME_MAX_LEN} 个字符`
  }

  return errors
}

export function RegisterPage() {
  const navigate = useNavigate()

  const [values, setValues] = useState<FormValues>(EMPTY_FORM)
  const [fieldErrors, setFieldErrors] = useState<Errors>({})
  const [formError, setFormError] = useState<string | null>(null)

  const mutation = useRegisterMutation()

  const setValue = (key: keyof FormValues) => (value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => withoutFieldError(prev, key))
    setFormError(null)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const errors = validate(values)
    setFieldErrors(errors)
    setFormError(null)
    if (Object.keys(errors).length > 0) return

    const email = values.email
    mutation.mutate(
      {
        email,
        username: values.username,
        password: values.password,
        // 空串转 null：后端语义是「没填」，不是「填了个空字符串」
        display_name: values.display_name || null,
      },
      {
        onSuccess: () => {
          // replace 而不是 push：注册表单已经完成使命，不该还能被「后退」翻出来
          navigate('/login', { replace: true, state: { registered: true, email } })
        },
        onError: (error) => {
          if (error instanceof ApiError) {
            // 40910 邮箱已注册 / 40911 用户名已占用 / 40010 · 40011 · 40012 领域校验失败
            // 都带 data.field，直接挂到对应输入框上
            const field = error.field
            if (field === 'email' || field === 'username' || field === 'password') {
              setFieldErrors(withFieldError(field, error.message))
              return
            }
            // 兜底：FastAPI 的 422（40000）没有 field，只能整表提示
            setFormError(error.message)
            return
          }
          setFormError('注册失败，请稍后重试')
        },
      },
    )
  }

  const pending = mutation.isPending

  return (
    <AuthShell
      subtitle="创建一个新账号"
      footer={
        <>
          已有账号？
          <Link to="/login" className="text-brand hover:underline">
            去登录
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate>
        {formError && <Alert tone="error">{formError}</Alert>}

        <TextField
          id="email"
          label="邮箱"
          type="email"
          value={values.email}
          onChange={setValue('email')}
          placeholder="you@example.com"
          autoComplete="email"
          error={fieldErrors.email}
          disabled={pending}
        />

        <TextField
          id="username"
          label="用户名"
          value={values.username}
          onChange={setValue('username')}
          placeholder="alice"
          autoComplete="username"
          maxLength={USERNAME_MAX_LEN}
          error={fieldErrors.username}
          disabled={pending}
          hint={`${USERNAME_MIN_LEN}~${USERNAME_MAX_LEN} 位字母、数字、下划线或连字符`}
        />

        <TextField
          id="password"
          label="密码"
          type="password"
          value={values.password}
          onChange={setValue('password')}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LEN}
          error={fieldErrors.password}
          disabled={pending}
          trim={false}
          hint={`${PASSWORD_MIN_LEN}~${PASSWORD_MAX_LEN} 个字符`}
        />

        <TextField
          id="confirm_password"
          label="确认密码"
          type="password"
          value={values.confirm_password}
          onChange={setValue('confirm_password')}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LEN}
          error={fieldErrors.confirm_password}
          disabled={pending}
          trim={false}
        />

        <TextField
          id="display_name"
          label="显示名（选填）"
          value={values.display_name}
          onChange={setValue('display_name')}
          placeholder="留空则使用用户名"
          maxLength={DISPLAY_NAME_MAX_LEN}
          error={fieldErrors.display_name}
          disabled={pending}
        />

        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-lg bg-brand py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {pending ? '注册中…' : '注册'}
        </button>
      </form>
    </AuthShell>
  )
}
