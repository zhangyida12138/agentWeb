import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { usersApi, type CreateUserPayload } from '../lib/api'

const usersQueryKey = ['users'] as const

export default function UsersPage() {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')

  const usersQuery = useQuery({
    queryKey: usersQueryKey,
    queryFn: () => usersApi.list(),
  })

  const createMutation = useMutation({
    mutationFn: (payload: CreateUserPayload) => usersApi.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersQueryKey })
      setEmail('')
      setDisplayName('')
    },
  })

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    createMutation.mutate({ email, display_name: displayName })
  }

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-bold">用户</h1>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          邮箱
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          昵称
          <input
            type="text"
            required
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            className="rounded border border-gray-300 px-3 py-2"
          />
        </label>
        <button
          type="submit"
          disabled={createMutation.isPending}
          className="rounded bg-brand px-4 py-2 text-white disabled:opacity-50"
        >
          {createMutation.isPending ? '提交中...' : '新增用户'}
        </button>
      </form>

      {createMutation.isError && (
        <p className="text-sm text-red-600">创建失败：{createMutation.error.message}</p>
      )}

      {usersQuery.isPending && <p className="text-gray-500">加载中...</p>}
      {usersQuery.isError && (
        <p className="text-sm text-red-600">加载失败：{usersQuery.error.message}</p>
      )}

      {usersQuery.data && usersQuery.data.length === 0 && <p className="text-gray-500">暂无用户</p>}

      {usersQuery.data && usersQuery.data.length > 0 && (
        <ul className="divide-y divide-gray-200 rounded border border-gray-200 bg-white">
          {usersQuery.data.map((user) => (
            <li key={user.id} className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="font-medium">{user.display_name}</p>
                <p className="text-sm text-gray-500">{user.email}</p>
              </div>
              <span className={user.is_active ? 'text-sm text-green-600' : 'text-sm text-gray-400'}>
                {user.is_active ? '启用' : '停用'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
