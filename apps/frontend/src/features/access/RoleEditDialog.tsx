import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'

import { Alert } from '../../components/Alert'
import { Modal } from '../../components/Modal'
import { ApiError } from '../../lib/api'
import { useAssignRolesMutation, useRolesQuery } from './hooks'
import type { UserWithRoles } from './types'

/**
 * 编辑某用户的角色（勾选框）。
 *
 * 交互上刻意做成「勾完再保存」，而不是「勾一下就立刻提交」：
 *   ① 后端是**替换**语义，一次提交一整个集合。逐次提交会把「把 admin 换成 author」
 *      拆成两步，中间那一瞬间该用户同时缺少两种角色的权限；
 *   ② 管理员改权限是会紧张的，给他一次「反悔」的机会比省一次点击重要。
 *
 * 提交时传的是「最终勾中的全部编码」而不是增删差异：
 *   与后端 PUT 的替换语义对齐，天然幂等，也免掉一份「我原本有什么」的差异计算。
 */

interface RoleEditDialogProps {
  target: UserWithRoles
  onClose: () => void
}

export function RoleEditDialog({ target, onClose }: RoleEditDialogProps) {
  const rolesQuery = useRolesQuery()
  const mutation = useAssignRolesMutation()

  // 初始勾选态来自列表数据（不是再发一次请求）：
  // 列表项本来就带着 role_codes，再 GET 一次既是多余往返，
  // 也可能读到「别人刚改过」的更新值，让管理员误以为自己看到的是现状
  const [selected, setSelected] = useState<Set<string>>(() => new Set(target.role_codes))
  const [formError, setFormError] = useState<string | null>(null)

  const initial = useMemo(() => new Set(target.role_codes), [target.role_codes])

  // 「有没有改动」必须比较集合内容，不能比引用：
  // 勾了再取消勾选，内容回到原样，引用却已经换了，按钮会永远亮着
  const isDirty = selected.size !== initial.size || [...selected].some((code) => !initial.has(code))

  const toggle = (code: string) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    setFormError(null)
    mutation.mutate(
      { userId: target.user.id, roleCodes: [...selected] },
      {
        onSuccess: () => onClose(),
        onError: (error) => {
          setFormError(error instanceof ApiError ? error.message : '保存失败，请稍后重试')
        },
      },
    )
  }

  return (
    <Modal
      title="编辑角色"
      description={`${target.user.display_name || target.user.username} · ${target.user.email}`}
      onClose={onClose}
    >
      {rolesQuery.isPending && <p className="text-sm text-gray-500">加载角色…</p>}

      {rolesQuery.error && (
        <Alert tone="error">
          {rolesQuery.error instanceof ApiError ? rolesQuery.error.message : '无法加载角色列表'}
        </Alert>
      )}

      {rolesQuery.data && (
        <form onSubmit={handleSubmit}>
          {formError && <Alert tone="error">{formError}</Alert>}

          <fieldset className="mb-4 flex flex-col gap-2">
            <legend className="mb-2 text-sm font-medium text-gray-700">可分配的角色</legend>

            {rolesQuery.data.map((role) => (
              <label
                key={role.code}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 p-3 transition-colors hover:bg-gray-50"
              >
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 accent-brand"
                  checked={selected.has(role.code)}
                  onChange={() => toggle(role.code)}
                  disabled={mutation.isPending}
                />
                <span className="flex-1">
                  <span className="block text-sm text-gray-900">
                    {role.name}
                    <span className="ml-2 text-xs text-gray-400">{role.code}</span>
                  </span>
                  {role.description && (
                    <span className="mt-0.5 block text-xs text-gray-500">{role.description}</span>
                  )}
                </span>
              </label>
            ))}
          </fieldset>

          {/*
            把「一个都不勾」的后果明说出来。它是合法操作（收回全部权限），
            但完全没有提示时，管理员很容易把它当成「暂时不改」而误点保存，
            结果把一个用户的所有权限清空了。
          */}
          {selected.size === 0 && (
            <Alert tone="info">未勾选任何角色 = 收回该用户的全部权限，他将无法做任何操作。</Alert>
          )}

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
              // 没有任何改动时禁用提交：既省一次无意义的请求，
              // 也避免「我明明没改」却触发一次替换、把 updated_at 白白推新
              disabled={mutation.isPending || !isDirty}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {mutation.isPending ? '保存中…' : '保存'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
