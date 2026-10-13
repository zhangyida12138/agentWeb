import { useState } from 'react'
import type { FormEvent } from 'react'

import { Alert } from '../../components/Alert'
import { TextAreaField, TextField } from '../../components/Field'
import { ApiError } from '../../lib/api'
import { withoutFieldError, withFieldError } from '../../lib/form'
import { useUpdateProfileMutation } from '../auth/hooks'

import type { AuthUser, UpdateProfileInput } from '../auth/types'

/**
 * 基本资料表单。
 *
 * 核心难点是 PATCH 语义，不是表单本身：
 *   后端用 `exclude_unset=True` 区分「没传这个字段」和「传了 null」，
 *   所以提交时**只能带上真正改过的键**。做法是记住一份 initial 快照，
 *   提交前 diff 出 patch；什么都不改时按钮直接禁用，连请求都不发。
 *
 *   空串 → 转成 null 提交，表示「清空」（后端 `_blank_to_none` 会收敛成 None）。
 */

interface Values {
  display_name: string
  avatar_url: string
  bio: string
}

/** 后端给的可空字段统一折成字符串，避免表单里到处写 `?? ''`。 */
function toValues(user: AuthUser): Values {
  return {
    display_name: user.display_name ?? '',
    avatar_url: user.avatar_url ?? '',
    bio: user.bio ?? '',
  }
}

function buildPatch(initial: Values, current: Values): UpdateProfileInput {
  const patch: UpdateProfileInput = {}
  // `current.x || null`：空串表示清空，转成 null 发给后端
  if (current.display_name !== initial.display_name) {
    patch.display_name = current.display_name || null
  }
  if (current.avatar_url !== initial.avatar_url) patch.avatar_url = current.avatar_url || null
  if (current.bio !== initial.bio) patch.bio = current.bio || null
  return patch
}

const MAX = { display_name: 64, avatar_url: 512, bio: 500 } as const

export function ProfileForm({ user }: { user: AuthUser }) {
  const [initial, setInitial] = useState<Values>(() => toValues(user))
  const [values, setValues] = useState<Values>(initial)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Values, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const mutation = useUpdateProfileMutation()
  const patch = buildPatch(initial, values)
  const dirty = Object.keys(patch).length > 0

  const setValue = (key: keyof Values) => (value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => withoutFieldError(prev, key))
    setFormError(null)
    setSaved(false)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!dirty) return

    setFieldErrors({})
    setFormError(null)

    mutation.mutate(patch, {
      onSuccess: () => {
        // 把新值确立为新的基线：这样「再改回去」会被正确识别为又一次修改，
        // 而不是误判成「没变化」。
        setInitial(values)
        setSaved(true)
      },
      onError: (error) => {
        if (error instanceof ApiError) {
          const field = error.field
          if (field === 'display_name' || field === 'avatar_url' || field === 'bio') {
            setFieldErrors(withFieldError(field, error.message))
            return
          }
          setFormError(error.message)
          return
        }
        setFormError('保存失败，请稍后重试')
      },
    })
  }

  const handleReset = () => {
    setValues(initial)
    setFieldErrors({})
    setFormError(null)
    setSaved(false)
  }

  const pending = mutation.isPending

  return (
    <form onSubmit={handleSubmit} noValidate>
      {formError && <Alert tone="error">{formError}</Alert>}
      {saved && !dirty && <Alert tone="success">资料已保存</Alert>}

      <TextField
        id="display_name"
        label="显示名"
        value={values.display_name}
        onChange={setValue('display_name')}
        placeholder={user.username}
        maxLength={MAX.display_name}
        error={fieldErrors.display_name}
        disabled={pending}
        hint="留空则显示为用户名"
      />

      <TextField
        id="avatar_url"
        label="头像地址"
        type="url"
        value={values.avatar_url}
        onChange={setValue('avatar_url')}
        placeholder="https://example.com/avatar.png"
        maxLength={MAX.avatar_url}
        error={fieldErrors.avatar_url}
        disabled={pending}
      />

      <TextAreaField
        id="bio"
        label="个人简介"
        value={values.bio}
        onChange={setValue('bio')}
        rows={4}
        maxLength={MAX.bio}
        placeholder="介绍一下自己…"
        error={fieldErrors.bio}
        disabled={pending}
      />

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={pending || !dirty}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {pending ? '保存中…' : '保存修改'}
        </button>
        <button
          type="button"
          onClick={handleReset}
          disabled={pending || !dirty}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          重置
        </button>
        {!dirty && !saved && <span className="text-xs text-gray-400">尚未修改任何内容</span>}
      </div>
    </form>
  )
}
