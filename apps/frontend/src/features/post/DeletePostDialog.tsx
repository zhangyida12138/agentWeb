import { useState } from 'react'

import { Alert } from '../../components/Alert'
import { Modal } from '../../components/Modal'
import { ApiError } from '../../lib/api'

import { useDeletePostMutation } from './hooks'

import type { PostSummary } from './types'

/**
 * 删除确认弹窗（详情页与「我的文章」共用）。
 *
 * 为什么删除必须二次确认、而下架不用：
 *   软删除之后 slug 仍然被占用（唯一索引不认 `deleted_at`），永久链接会 404，
 *   而且「删了再发一篇同标题的」拿到的是带序号的 slug，不是原来那个地址。
 *   **下架是可逆的**（文章还在我的文章里，随时能重新发布），
 *   删除在用户视角是不可逆的——不可逆的操作必须有一步停顿。
 *
 * 失败时弹窗**保持打开**并把错误显示在里面（而不是关掉、把错误丢给页面）：
 *   用户此刻的意图是「删掉这篇」，失败了就该让他能直接重试或取消，
 *   关掉弹窗等于让他的意图凭空消失，还得重新找一次入口。
 */
export function DeletePostDialog({
  post,
  onClose,
  onDeleted,
}: {
  post: Pick<PostSummary, 'id' | 'slug' | 'title'>
  onClose: () => void
  /**
   * 删除成功后调用的收尾动作。
   *
   * 详情页必须传（那个 slug 已经 404，页面不能停留）；列表页不用传，就地刷新列表即可。
   * 做成回调而不是组件内部 navigate：组件不该假设自己出现在哪个页面上。
   */
  onDeleted?: () => void
}) {
  const deleteMutation = useDeletePostMutation()
  const [error, setError] = useState<string | null>(null)

  const handleConfirm = () => {
    setError(null)
    deleteMutation
      .mutateAsync({ postId: post.id, slug: post.slug })
      .then(() => {
        onClose()
        onDeleted?.()
      })
      .catch((caught: unknown) => {
        setError(caught instanceof ApiError ? caught.message : '删除失败，请稍后重试')
      })
  }

  return (
    <Modal
      title="删除这篇文章？"
      description="删除后永久链接会失效，且无法恢复。"
      onClose={onClose}
    >
      <div className="flex flex-col gap-4">
        {error && <Alert tone="error">{error}</Alert>}

        <p className="text-sm text-gray-600">
          「{post.title}」将被删除。如果你只是不想让它出现在公开列表里，用「下架」更合适——
          文章会留在「我的文章」里，随时可以重新发布。
        </p>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={deleteMutation.isPending}
            onClick={handleConfirm}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            {deleteMutation.isPending ? '删除中…' : '确认删除'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
