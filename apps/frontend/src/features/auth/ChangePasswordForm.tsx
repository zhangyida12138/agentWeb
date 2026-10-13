import { useState } from 'react'
import type { FormEvent } from 'react'

import { Alert } from '../../components/Alert'
import { TextField } from '../../components/Field'
import { ApiError } from '../../lib/api'
import { withoutFieldError, withFieldError } from '../../lib/form'

import { useChangePasswordMutation } from './hooks'

/**
 * 修改密码表单（由 ChangePasswordPage 承载）。
 *
 * 前端只做「三次输入一致」「长度合规」这类**本地就能判定**的校验；
 * 「旧密码对不对」必须问后端（见 ChangePasswordUseCase，它要求旧密码二次确认，
 * 否则任何一个被窃取的 token 都能直接改密把机主锁在门外）。
 *
 * 长度口径与后端 schema 对齐：8~64 个字符。注意后端还有一层 bcrypt 的 72 **字节**
 * 限制——那是汉字才会踩到的坑，由后端的 WeakPasswordError 兜底，前端不重复实现。
 *
 * 放在 features/auth 而不是 profile：它调用的是 `/auth/change-password`，
 * 属于「认证」这件事，个人中心只是入口之一。
 */

const PASSWORD_MIN_LEN = 8
const PASSWORD_MAX_LEN = 64

interface Values {
  old_password: string
  new_password: string
  confirm_password: string
}

const EMPTY_FORM: Values = { old_password: '', new_password: '', confirm_password: '' }

type Errors = Partial<Record<keyof Values, string>>

function validate(values: Values): Errors {
  const errors: Errors = {}
  if (!values.old_password) errors.old_password = '请输入当前密码'

  if (!values.new_password) errors.new_password = '请输入新密码'
  else if (values.new_password.length < PASSWORD_MIN_LEN) {
    errors.new_password = `新密码至少 ${PASSWORD_MIN_LEN} 个字符`
  } else if (values.new_password.length > PASSWORD_MAX_LEN) {
    errors.new_password = `新密码最多 ${PASSWORD_MAX_LEN} 个字符`
  } else if (values.new_password === values.old_password) {
    // 不是安全要求，纯粹是「改了等于没改」的体验提示
    errors.new_password = '新密码不能与当前密码相同'
  }

  if (!values.confirm_password) errors.confirm_password = '请再次输入新密码'
  else if (values.confirm_password !== values.new_password) {
    errors.confirm_password = '两次输入的新密码不一致'
  }

  return errors
}

export function ChangePasswordForm() {
  const [values, setValues] = useState<Values>(EMPTY_FORM)
  const [fieldErrors, setFieldErrors] = useState<Errors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const mutation = useChangePasswordMutation()

  const setValue = (key: keyof Values) => (value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => withoutFieldError(prev, key))
    setFormError(null)
    setDone(false)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const errors = validate(values)
    setFieldErrors(errors)
    setFormError(null)
    if (Object.keys(errors).length > 0) return

    mutation.mutate(
      { old_password: values.old_password, new_password: values.new_password },
      {
        onSuccess: () => {
          // 成功后立刻清空输入框：密码明文不该在 DOM 里多留一秒
          setValues(EMPTY_FORM)
          setDone(true)
        },
        onError: (error) => {
          if (error instanceof ApiError) {
            // 后端的 WeakPasswordError 带 data.field === 'password'，映射到新密码框
            if (error.field === 'password') {
              setFieldErrors(withFieldError('new_password', error.message))
              return
            }
            // InvalidCredentialsError「原密码不正确」没有 field，落在顶部提示条上。
            // 注意它是 401 + 40110，但**不代表登录态失效**——lib/api.ts 里特意把它
            // 排除在 clearAuth 之外，否则用户只是打错一次旧密码就会被登出。
            setFormError(error.message)
            return
          }
          setFormError('修改失败，请稍后重试')
        },
      },
    )
  }

  const pending = mutation.isPending

  return (
    <form onSubmit={handleSubmit} noValidate>
      {formError && <Alert tone="error">{formError}</Alert>}
      {done && <Alert tone="success">密码已修改</Alert>}

      <TextField
        id="old_password"
        label="当前密码"
        type="password"
        value={values.old_password}
        onChange={setValue('old_password')}
        autoComplete="current-password"
        error={fieldErrors.old_password}
        disabled={pending}
        trim={false}
      />

      <TextField
        id="new_password"
        label="新密码"
        type="password"
        value={values.new_password}
        onChange={setValue('new_password')}
        autoComplete="new-password"
        maxLength={PASSWORD_MAX_LEN}
        error={fieldErrors.new_password}
        disabled={pending}
        trim={false}
        hint={`${PASSWORD_MIN_LEN}~${PASSWORD_MAX_LEN} 个字符`}
      />

      <TextField
        id="confirm_password"
        label="确认新密码"
        type="password"
        value={values.confirm_password}
        onChange={setValue('confirm_password')}
        autoComplete="new-password"
        maxLength={PASSWORD_MAX_LEN}
        error={fieldErrors.confirm_password}
        disabled={pending}
        trim={false}
      />

      <button
        type="submit"
        disabled={pending}
        className="rounded-lg border border-brand px-4 py-2 text-sm font-medium text-brand transition-colors hover:bg-purple-50 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {pending ? '提交中…' : '修改密码'}
      </button>
    </form>
  )
}
