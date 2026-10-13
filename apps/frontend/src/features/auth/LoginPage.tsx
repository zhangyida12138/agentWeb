import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { TextField } from '../../components/Field'
import { ApiError } from '../../lib/api'
import { withoutFieldError, withFieldError } from '../../lib/form'
import { setAuth, useAuth } from '../../stores/auth'

import { AuthShell } from './AuthShell'
import { login } from './api'

/**
 * 登录页。
 *
 * 三件事分开表达，互不干扰：
 *   ① 字段级错误（fieldErrors）→ 挂在具体输入框下面
 *   ② 整表错误（formError）   → 顶部提示条，如「邮箱或密码错误」
 *   ③ 提交中（isPending）     → 按钮禁用 + 文案变化，防重复提交
 *
 * 注意「记住登录状态」这类开关一律不做：token 的存放位置（localStorage）
 * 是安全与体验的权衡结果，做成用户可勾选的选项等于把风险决策丢给用户。
 *
 * 注册成功后会带着 `state.registered` 跳回这里（注册接口不签发 token），
 * 于是要做两件事：显示一句成功提示、把邮箱预填好，让用户只差输入密码。
 */

/** 从注册页带过来的路由状态。 */
interface LoginLocationState {
  registered?: boolean
  email?: string
}

interface FormValues {
  email: string
  password: string
}

/** 只做「明显写错」的拦截。真正的格式校验在后端 schema 与应用层，前端不重复实现规则。 */
function validate(values: FormValues): Partial<Record<keyof FormValues, string>> {
  const errors: Partial<Record<keyof FormValues, string>> = {}
  if (!values.email) errors.email = '请输入邮箱'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) errors.email = '邮箱格式不正确'
  // 刻意不校验密码长度：注册页的密码策略不该在登录口被回显（后端同样如此设计）
  if (!values.password) errors.password = '请输入密码'
  return errors
}

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // 初始化函数里读一次即可：路由 state 不会在停留期间变化，
  // 而且这里要的是「进入页面那一刻的预填值」，不是持续同步
  const [values, setValues] = useState<FormValues>(() => ({
    email: (location.state as LoginLocationState | null)?.email ?? '',
    password: '',
  }))
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof FormValues, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)

  // 只有从注册页跳回来才显示成功提示；用户手动打错地址进来时不该看到这句话
  const registered = (location.state as LoginLocationState | null)?.registered === true

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (result) => {
      setAuth(result.token, result.user)

      // 回到「被踢出前想去的地方」。RequireAuth 拦截时会把原路径放进 state.from，
      // 直接进登录页则没有 from，回首页。
      const from = (location.state as { from?: string } | null)?.from ?? '/'
      // replace：登录页不该留在历史里，否则登录后按「后退」会回到一张空表单
      navigate(from, { replace: true })
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        // 后端在 data.field 里指了字段就挂到那个输入框（如 40010 → email）
        const field = error.field
        if (field === 'email' || field === 'password') {
          setFieldErrors(withFieldError(field, error.message))
          return
        }
        setFormError(error.message)
        return
      }
      setFormError('登录失败，请稍后重试')
    },
  })

  // 已登录用户直接放行，避免手输 /login 时看到一张无意义的表单
  if (auth.token) return <Navigate to="/" replace />

  const setValue = (key: keyof FormValues) => (value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    // 用户开始改了就把这个字段和顶部的旧错误清掉，不让红字一直挂着
    setFieldErrors((prev) => withoutFieldError(prev, key))
    setFormError(null)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const errors = validate(values)
    setFieldErrors(errors)
    setFormError(null)
    if (Object.keys(errors).length > 0) return

    mutation.mutate({ email: values.email, password: values.password })
  }

  const pending = mutation.isPending

  return (
    <AuthShell
      subtitle="登录后开始使用"
      footer={
        <>
          还没有账号？
          <Link to="/register" className="text-brand hover:underline">
            立即注册
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate>
        {registered && <Alert tone="success">注册成功，请使用刚才设置的密码登录</Alert>}
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
          id="password"
          label="密码"
          type="password"
          value={values.password}
          onChange={setValue('password')}
          placeholder="请输入密码"
          autoComplete="current-password"
          error={fieldErrors.password}
          disabled={pending}
          trim={false}
        />

        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-lg bg-brand py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {pending ? '登录中…' : '登录'}
        </button>
      </form>
    </AuthShell>
  )
}
