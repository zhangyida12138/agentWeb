import { useState } from 'react'

import { Alert } from '../../components/Alert'
import { TextAreaField, TextField } from '../../components/Field'
import { Modal } from '../../components/Modal'
import { ApiError } from '../../lib/api'
import { withFieldError, withoutFieldError } from '../../lib/form'
import { useCreateTagMutation, useUpdateTagMutation } from './hooks'
import {
  TAG_DESCRIPTION_MAX_LEN,
  TAG_NAME_MAX_LEN,
  TAG_TYPE_LABEL,
  tagDescriptionError,
  tagNameError,
  toFormField,
} from './types'

import type { FieldErrors } from '../../lib/form'
import type { Tag, TagTypeValue } from './types'

/**
 * 标签的「新建 / 编辑」表单弹窗。
 *
 * ── 为什么两个入口共用一个文件 ──
 * 新建与编辑的差别只有三处：标题、调哪个 mutation、**新建时多一个 type 选择**。
 * 而它们的**共同点**才是真正需要写对的地方：
 *   · 字段布局与字数计数
 *   · 提交前的前端校验（名字形状、描述长度）
 *   · 后端错误码到输入框的挂载（见下方 `toFormField` 的说明）
 *   · 「失败不关弹窗」的处理
 * 把这几条抄两份，等于把「下次改校验规则时要改两处」这件事制度化。
 * 后端那边其实也是同一个 `Tag` 实体在承担两种入参，这里只是跟着它的形状走。
 *
 * ── 失败时弹窗必须保持打开 ──
 * 与 DeletePostDialog 同一条理由、但在表单上更要紧：
 * 用户此刻的意图是「把这个名字改掉」，失败了就该让他能直接在原值上改一个字再提交。
 * 关掉弹窗等于把他的输入全部丢掉，还得重新找一次入口、重新打一遍。
 * 所以错误要么挂到具体输入框（用户知道改哪个字），要么显示在弹窗内的顶部（知道为什么）。
 */

type FieldKey = 'name' | 'description'

interface TagFormProps {
  title: string
  /** 副标题。可选，因为"编辑用户标签"没有需要额外说明的事。 */
  description: string | undefined
  initialName: string
  initialDescription: string
  /** 新建时给出可选的类型列表；编辑时传 undefined（类型不可改）。 */
  typeOptions?: readonly TagTypeValue[]
  submitLabel: string
  onClose: () => void
  onSaved?: () => void
  onSubmit: (values: {
    name: string
    description: string | null
    type: TagTypeValue
  }) => Promise<void>
  isPending: boolean
}

/**
 * 表单主体。两个对外的对话框都只是「往这里塞不同的 onSubmit」。
 *
 * `ApiError.field` → 本地字段名的映射交给 `toFormField`，不在这里写 if：
 * 后端对"名字"的问题会给出 `name`（撞车，40950）和 `tag_names`（格式非法，40036）
 * 两个不同的 field，漏掉任一个都会让错误掉进"整表错误"分支。
 */
function TagForm({
  title,
  description,
  initialName,
  initialDescription,
  typeOptions,
  submitLabel,
  onClose,
  onSaved,
  onSubmit,
  isPending,
}: TagFormProps) {
  // 受控状态放这里而不是调用方：调用方（页面）不该关心"用户打了一半的名字"，
  // 它只关心"编辑哪个标签"。弹窗关闭时这份中间态随之消失，符合直觉。
  const [name, setName] = useState(initialName)
  const [tagDescription, setTagDescription] = useState(initialDescription)
  const [type, setType] = useState<TagTypeValue>(typeOptions?.[0] ?? 'user')
  const [errors, setErrors] = useState<FieldErrors<FieldKey>>({})
  const [formError, setFormError] = useState<string | null>(null)

  // 输入时清掉该字段的错误：让用户看到的红字始终对应他**当前**的内容。
  // 不清的话，"名称不能包含 #" 会一直红到他提交成功为止，即使他早就删掉了 #。
  const changeName = (next: string) => {
    setName(next)
    setErrors((prev) => withoutFieldError(prev, 'name'))
  }
  const changeDescription = (next: string) => {
    setTagDescription(next)
    setErrors((prev) => withoutFieldError(prev, 'description'))
  }

  const handleSubmit = async () => {
    setFormError(null)

    // 前端先跑一遍校验：不是为了拦住后端（那是值对象的职责），
    // 而是为了省掉一次注定失败的往返。校验函数与后端正则逐字对齐，见 types.ts。
    const nameError = tagNameError(name)
    const descriptionError = tagDescriptionError(tagDescription)
    if (nameError || descriptionError) {
      setErrors({
        ...(nameError ? withFieldError('name', nameError) : {}),
        ...(descriptionError ? withFieldError('description', descriptionError) : {}),
      })
      return
    }

    setErrors({})
    try {
      await onSubmit({
        name: name.trim(),
        // 空描述提交成 null：后端 `change_description(None)` 的语义是**清空**。
        // 这里不能传空串——`TagDescription("")` 会抛 40050（"不能为空"），
        // 而后端那侧的 `normalize_description` 才负责把空串折叠成 None。
        // 也就是说传空串能跑，但那是"靠后端兜住"，前端不该依赖它。
        description: tagDescription.trim() || null,
        type,
      })
      onClose()
      onSaved?.()
    } catch (error) {
      if (!(error instanceof ApiError)) {
        setFormError('保存失败，请稍后重试')
        return
      }
      const field = toFormField(error.field)
      if (field) {
        setErrors(withFieldError(field, error.message))
        return
      }
      // 没有 field 的错误：40350（不是你的）、40051（系统标签谁都改不了）、
      // 40950 之外的冲突等。它们描述的是"这个对象现在的状态"而不是"你哪个字段填错了",
      // 挂到输入框上会让用户反复检查一个正确的输入。显示在顶部才是诚实的。
      setFormError(error.message)
    }
  }

  return (
    <Modal title={title} description={description} onClose={onClose}>
      <div className="flex flex-col gap-1">
        {formError && <Alert tone="error">{formError}</Alert>}

        <TextField
          id="tag-name"
          label="标签名"
          value={name}
          onChange={changeName}
          placeholder="例如 机器学习"
          maxLength={TAG_NAME_MAX_LEN}
          required
          disabled={isPending}
          error={errors.name}
          hint="名称决定网址部分（slug）：改名会改变它，已经发出去的筛选链接会失效。"
          // 打开即输入：Modal 没有焦点陷阱，autoFocus 是调用方唯一能提供的"能直接打字"体验
          autoFocus
        />

        <TextAreaField
          id="tag-description"
          label="描述"
          value={tagDescription}
          onChange={changeDescription}
          rows={3}
          maxLength={TAG_DESCRIPTION_MAX_LEN}
          placeholder="这个标签是给什么内容用的（可留空）"
          disabled={isPending}
          error={errors.description}
          hint="留空表示不要描述；清空已有描述同样是「留空后保存」。"
        />

        {typeOptions && (
          <div className="mb-4">
            <label htmlFor="tag-type" className="mb-1 block text-sm font-medium text-gray-700">
              类型
            </label>
            <select
              id="tag-type"
              name="tag-type"
              value={type}
              onChange={(event) => setType(event.target.value as TagTypeValue)}
              disabled={isPending}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-purple-100 disabled:bg-gray-100"
            >
              {typeOptions.map((option) => (
                <option key={option} value={option}>
                  {TAG_TYPE_LABEL[option]}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-500">
              官方标签只有管理员能改——它通常是产品预置的入口。
            </p>
          </div>
        )}

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
            disabled={isPending}
            onClick={() => void handleSubmit()}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            {isPending ? '保存中…' : submitLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/**
 * 新建标签（**管理员专享**）。
 *
 * 这个限制不是前端的懒省事，而是后端 `POST /tags` 上挂着 `tag:manage`。
 * 那么"作者怎么会有自己的标签"？答案是：写文章时用到一个新的标签名，
 * 文章那条链路（`post:create`）会顺带建出这个标签并把 `author_id` 记成作者，
 * 之后再回到这里改它的名字和描述——**归属来自"第一次用它"，
 * 而不是来自"申请一个标签"**。产品上这是一条更短的路径：
 * 作者不需要先有术语表才能写作。
 */
export function CreateTagDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void
  onSaved?: () => void
}) {
  const createMutation = useCreateTagMutation()

  return (
    <TagForm
      title="新建标签"
      description="新建的标签默认是「正常」状态，立刻可以被文章使用。"
      initialName=""
      initialDescription=""
      // 用数组而不是写死两个 option：将来若加了 `topic`/`series` 之类的类型，
      // 改动只在这个列表里，而不会散在 JSX 中
      typeOptions={['user', 'system']}
      submitLabel="创建"
      isPending={createMutation.isPending}
      onClose={onClose}
      onSaved={onSaved}
      onSubmit={async (values) => {
        await createMutation.mutateAsync({
          name: values.name,
          description: values.description,
          type: values.type,
        })
      }}
    />
  )
}

/**
 * 编辑标签（作者改自己的 / 管理员改任意用户标签）。
 *
 * **不在这里判断权限**：能不能编辑由调用方（页面）用
 * `canEditTag(codes, tag, me)` 决定，决定不了就不渲染这个弹窗。
 * 弹窗内部再判一次的话，"为什么这个按钮点了没反应"会多出一个可能原因。
 *
 * 类型不可改（`typeOptions` 不传），因为这正是后端的行为：
 * `UpdateTagCommand` 里根本没有 type 字段，`Tag` 的 `_replace` 也没在改它。
 * 前端露出一个后端不接受的输入框，用户改完保存发现没生效——比不给这个框更糟。
 */
export function EditTagDialog({
  tag,
  onClose,
  onSaved,
}: {
  tag: Tag
  onClose: () => void
  onSaved?: () => void
}) {
  const updateMutation = useUpdateTagMutation()

  return (
    <TagForm
      title={`编辑标签「${tag.name}」`}
      description={
        tag.type === 'system' ? '这是官方标签，改名会影响所有引用它的文章与首页入口。' : undefined
      }
      initialName={tag.name}
      initialDescription={tag.description ?? ''}
      submitLabel="保存"
      isPending={updateMutation.isPending}
      onClose={onClose}
      onSaved={onSaved}
      onSubmit={async (values) => {
        await updateMutation.mutateAsync({
          tagId: tag.id,
          input: { name: values.name, description: values.description },
        })
      }}
    />
  )
}
