import { useState } from 'react'
import type { FormEvent } from 'react'

import { Alert } from '../../components/Alert'
import { TextField } from '../../components/Field'
import { Modal } from '../../components/Modal'
import { ApiError } from '../../lib/api'
import { withoutFieldError, withFieldError } from '../../lib/form'
import type { FieldErrors } from '../../lib/form'
import { useResetUserPasswordMutation } from './hooks'
import type { UserWithRoles } from './types'

/**
 * 管理员为某用户设定新密码。
 *
 * 两次输入 + 前后端双重长度校验，是因为这个操作**没有回头路**：
 *   管理员自己敲错了新密码，用户拿到的就是一串谁也登不上的字符，
 *   而且管理员无从验证（他不能用别人的账号试登录）。
 *   前端拦「不一致 / 太短」这类一眼可见的错误，后端拦「绕过前端直接构造请求」。
 *
 * 这里刻意**不做**「生成随机密码」：
 *   随机密码要经过剪贴板 / 聊天软件转达，往往比管理员自拟的还难记、
 *   还会被顺手存进某个聊天记录。与其造一个用户记不住的密码，
 *   不如让他设一个自己能记住的、登录后立刻改成自己的。
 */

const PASSWORD_MIN_LEN = 8
const PASSWORD_MAX_LEN = 64

interface FormValues {
  new_password: string
  confirm_password: string
}

const EMPTY_FORM: FormValues = { new_password: '', confirm_password: '' }

/**
 * 只做「明显写错」的拦截。
 *
 * 长度上下限与后端 `schemas/auth.py` 的常量保持一致；
 * 这里**不**加「必须含大小写 + 数字」之类的复杂度规则——
 * 那类规则会把用户逼向 `Password1!` 这种更好猜的密码，
 * 而且真正的强度策略应该由后端一处定义，前端抄一份只会漂移。
 */
function validate(values: FormValues): FieldErrors<keyof FormValues> {
  let errors: FieldErrors<keyof FormValues> = {}

  const password = values.new_password
  if (!password) errors = withFieldError('new_password', '请输入新密码')
  else if (password.length < PASSWORD_MIN_LEN)
    errors = withFieldError('new_password', `新密码至少 ${PASSWORD_MIN_LEN} 位`)
  else if (password.length > PASSWORD_MAX_LEN)
    errors = withFieldError('new_password', `新密码最多 ${PASSWORD_MAX_LEN} 位`)

  if (!values.confirm_password) errors = withFieldError('confirm_password', '请再次输入新密码')
  else if (values.confirm_password !== values.new_password)
    errors = withFieldError('confirm_password', '两次输入的密码不一致')

  return errors
}

interface ResetPasswordDialogProps {
  target: UserWithRoles
  /** 当前登录者是不是就是目标用户，用来提示「你正在改自己的密码」 */
  isSelf: boolean
  onClose: () => void
}

export function ResetPasswordDialog({ target, isSelf, onClose }: ResetPasswordDialogProps) {
  const mutation = useResetUserPasswordMutation()

  const [values, setValues] = useState<FormValues>(EMPTY_FORM)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<keyof FormValues>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const setField = (field: keyof FormValues, value: string) => {
    setValues((previous) => ({ ...previous, [field]: value }))
    // 用户一开始重新输入就把该字段的报错清掉，别让红字挂在那儿干扰
    setFieldErrors((previous) => withoutFieldError(previous, field))
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    setFormError(null)

    const errors = validate(values)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    mutation.mutate(
      { userId: target.user.id, newPassword: values.new_password },
      {
        // 成功后**不自动关闭**：管理员需要一句明确的「已经改好了」
        // 才敢把密码告诉用户。自动关窗会让他不确定到底提交成功没有，
        // 然后再点一次——于是又改一遍密码。
        onSuccess: () => setDone(true),
        onError: (error) => {
          if (error instanceof ApiError) {
            // 后端把出错的字段名放在 data.field 里（本项目统一的错误契约）
            if (error.field === 'new_password') {
              setFieldErrors(withFieldError('new_password', error.message))
            } else {
              setFormError(error.message)
            }
          } else {
            setFormError('重置失败，请稍后重试')
          }
        },
      },
    )
  }

  const displayName = target.user.display_name || target.user.username

  if (done) {
    return (
      <Modal title="密码已重置" onClose={onClose}>
        <Alert tone="success">
          已为 <strong>{displayName}</strong> 设定新密码。
        </Alert>

        {/*
          这条提示是**必须**的，不是客套话：
          后端的 access token 是无状态 JWT，服务端不留会话，
          所以重置密码不会让该用户已登录的设备下线。
          不说清楚，管理员会把「重置密码」当成「踢人下线」来用，
          以为账号已经被保护住了——这是实打实的误判。
        */}
        <p className="mb-4 text-xs text-gray-500">
          请把新密码告知该用户，并提醒他登录后立即自行修改。
          注意：重置密码不会让该用户已登录的设备立即下线，其登录状态会一直保持到令牌过期。
        </p>

        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            完成
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title="重置密码" description={`${displayName} · ${target.user.email}`} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {formError && <Alert tone="error">{formError}</Alert>}

        {isSelf && (
          <Alert tone="info">
            你正在重置<strong>自己</strong>
            的密码。保存后请用新密码重新登录，当前登录状态不会失效。
          </Alert>
        )}

        <TextField
          id="new_password"
          label="新密码"
          type="password"
          value={values.new_password}
          onChange={(value) => setField('new_password', value)}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LEN}
          // 密码里可能有前导/尾随空格，trim 会悄悄改掉用户输入的密码
          trim={false}
          disabled={mutation.isPending}
          error={fieldErrors.new_password}
          hint={`${PASSWORD_MIN_LEN}-${PASSWORD_MAX_LEN} 位`}
        />

        <TextField
          id="confirm_password"
          label="确认新密码"
          type="password"
          value={values.confirm_password}
          onChange={(value) => setField('confirm_password', value)}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LEN}
          trim={false}
          disabled={mutation.isPending}
          error={fieldErrors.confirm_password}
        />

        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={mutation.isPending}
            className="rounded-lg px-4 py-2 text-sm text-gray-600 transition-colors hover:text-gray-900 disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {mutation.isPending ? '提交中…' : '确认重置'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
