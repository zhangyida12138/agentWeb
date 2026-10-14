import { useState, type FormEvent } from 'react'

import { TextAreaField } from '../../components/Field'
import { ApiError } from '../../lib/api'

import { useCreateCommentMutation } from './hooks'
import { COMMENT_CONTENT_MAX_LEN } from './types'

/**
 * 发表评论 / 回复的表单。
 *
 * 一个组件覆盖两种场景（根评论、回复），靠 `parentId` 区分，而不是写两份表单：
 *   两者的差别只有「往哪个 parent_id 发」和「按钮上写什么字」，
 *   分成两个组件就要把校验、错误映射、禁用状态各写两遍，
 *   而这两份实现一定会漂移（比如一个支持 Ctrl+Enter、另一个忘了）。
 *
 * 后端的校验分成两层，表单必须知道这个分层才能给出准确的提示：
 *   空串（长度 0）被 Pydantic 的 `min_length=1` 拦下 → **40000**
 *   「全是空白的串」能过 Pydantic，到领域里被 `CommentContent` strip 后为空 → **40040**
 * 两者后端给的 `message` 不同、且 40040 带 `data.field = 'content'`。
 * 所以这里不自己编提示语，直接把 `ApiError.message` 显示在输入框下面——
 * 一旦后端改了措辞，界面自动跟着变，不会出现「说法不一致的两套错误文案」。
 *
 * ⚠️ 本地只挡「空白」这一种：空白提交无论怎么算都是错的，
 *    拦下来能省一次必然失败的往返。除此之外**不**做长度、字数的本地校验，
 *    因为 maxLength 已经让超长打不出来了，再加一层只会和 `maxLength` 的语义重复。
 */

interface CommentFormProps {
  postId: string
  /** 要回复的评论 id。不传 = 发表根评论。 */
  parentId?: string
  /** 提交成功后的回调（根评论表单用它清空输入框并收起回复框）。 */
  onDone?: () => void
  /** 收起回复框（回复表单上的「取消」）。 */
  onCancel?: () => void
  placeholder?: string
}

export function CommentForm({
  postId,
  parentId,
  onDone,
  onCancel,
  placeholder = '说点什么…',
}: CommentFormProps) {
  const [content, setContent] = useState('')
  const [fieldError, setFieldError] = useState<string | undefined>(undefined)
  const mutation = useCreateCommentMutation(postId)

  const isReply = parentId !== undefined
  const fieldId = isReply ? `reply-${parentId}` : 'comment-new'

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    // 已知的必然失败：空白内容连一个 HTTP 往返都不值得发
    if (content.trim() === '') {
      setFieldError('评论内容不能为空')
      return
    }

    setFieldError(undefined)
    try {
      // 不 trim 后再发：后端会 strip，而内部的换行必须原样保留
      await mutation.mutateAsync({ content, parent_id: parentId })
      setContent('')
      onDone?.()
    } catch (error) {
      // 40040 带 data.field='content'，40000 也可能带（schema 层的定位）
      // 两种情况都落到同一个输入框上，所以这里不按 field 分流，只按「有没有 message」。
      setFieldError(error instanceof ApiError ? error.message : '发表失败，请稍后重试')
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-2">
      <TextAreaField
        id={fieldId}
        label={isReply ? '回复' : '发表评论'}
        value={content}
        onChange={(value) => {
          setContent(value)
          // 一边打字一边把上一次的错误收掉：错误留在屏幕上会让人以为还没改好
          if (fieldError) setFieldError(undefined)
        }}
        rows={isReply ? 3 : 4}
        maxLength={COMMENT_CONTENT_MAX_LEN}
        placeholder={placeholder}
        disabled={mutation.isPending}
        error={fieldError}
      />

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? '发表中…' : isReply ? '回复' : '发表'}
        </button>

        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={mutation.isPending}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            取消
          </button>
        )}
      </div>
    </form>
  )
}
