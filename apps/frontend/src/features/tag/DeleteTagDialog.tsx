import { useState } from 'react'

import { Alert } from '../../components/Alert'
import { Modal } from '../../components/Modal'
import { ApiError } from '../../lib/api'
import { useDeleteTagMutation } from './hooks'

import type { Tag } from './types'

/**
 * 删除标签的确认弹窗（仅管理员）。
 *
 * ── 为什么删除需要二次确认，而下架/恢复不需要 ──
 * 「下架」和「恢复」是同一个动作的两个方向，随时可以再点回来；
 * 「删除」在用户视角是不可逆的（虽然后端是软删除，而且 `PATCH /status`
 * 技术上能把 deleted 改回 normal——**但这条出路不该出现在这个弹窗里**，
 * 否则它就不是一次确认，而是一次"随便点点看"）。
 * 不可逆的操作需要一步停顿，这是弹窗存在的唯一理由。
 *
 * ── 文案要讲的两件事 ──
 * ① 删除会作用到**读路径**上：已删除的标签对包括文章详情在内的所有读取都不可见。
 *    所以「删掉一个没人用的垃圾标签」和「删掉一个被 50 篇文章使用的标签」
 *    后果完全不同——后者会从那些文章上一起消失。
 * ② 名字**仍然被占用**：后端的唯一性检查（`exists_name`/`exists_slug`）
 *    刻意不过滤状态，软删除的标签仍然占着 `ix_tags_name`。
 *    不提这一点的话，用户删完想重建一个同名的会撞 40950，然后完全无法理解。
 *
 * 失败时保持打开并就地显示错误，理由同 DeletePostDialog：
 * 此刻用户的意图是"删掉它"，失败了就该能直接重试或取消。
 */
export function DeleteTagDialog({
  tag,
  onClose,
  onDeleted,
}: {
  tag: Pick<Tag, 'id' | 'name' | 'post_count'>
  onClose: () => void
  /**
   * 删除成功后的收尾动作。
   * 做成回调而不是组件内部刷新列表：组件不该假设自己出现在哪个页面上
   * （列表要刷新、筛选计数要变、将来若有详情页要跳走）。
   */
  onDeleted?: () => void
}) {
  const deleteMutation = useDeleteTagMutation()
  const [error, setError] = useState<string | null>(null)

  const handleConfirm = () => {
    setError(null)
    deleteMutation
      .mutateAsync(tag.id)
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
      title="删除这个标签？"
      description="删除后它不再出现在任何列表、联想与文章中，且无法从界面恢复。"
      onClose={onClose}
    >
      <div className="flex flex-col gap-4">
        {error && <Alert tone="error">{error}</Alert>}

        <p className="text-sm text-gray-600">
          「{tag.name}」将被删除。
          {tag.post_count > 0 && (
            <>
              它当前被 <span className="font-medium">{tag.post_count}</span> 篇已发布文章使用，
              删除后这些文章上也会看不到它。
            </>
          )}
        </p>

        <p className="text-sm text-gray-600">
          如果你只是不想让人继续用它，用「下架」更合适——已有的文章不受影响，随时能恢复。
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
