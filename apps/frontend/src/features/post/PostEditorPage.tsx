import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Alert } from '../../components/Alert'
import { TextAreaField, TextField } from '../../components/Field'
import { ApiError } from '../../lib/api'
import { withoutFieldError, withFieldError } from '../../lib/form'
import { useAuth } from '../../stores/auth'
import { useMyAccessQuery } from '../access/hooks'

import {
  useCreatePostMutation,
  usePostQuery,
  usePublishPostMutation,
  useUpdatePostMutation,
} from './hooks'
import { MarkdownContent } from './MarkdownContent'
import { canEditPost } from './permissions'
import { PostStatusBadge } from './PostStatusBadge'

import type { FieldErrors } from '../../lib/form'
import type { CreatePostInput, PostDetail, UpdatePostInput } from './types'

/**
 * 文章编辑器：新建（`/editor`）与编辑（`/editor/:slug`）同一个组件。
 *
 * 两者共用一套表单是刻意的——新建和编辑的输入**完全一样**，
 * 分成两个组件唯一的后果是「给编辑页加了个字段，忘了给新建页加」。
 * 差别只在提交那一步：一个 POST、一个 PATCH。
 *
 * 这个页面有两处细节值得记住，它们都是和后端契约咬合的：
 *
 * ① **PATCH 只提交脏字段**
 *    后端用 `model_dump(exclude_unset=True)` 区分「没提这个字段」和「明确清空」。
 *    所以这里绝不能写 `updatePost(post.id, {...values})`：
 *    那等于把摘要、封面、标签的当前值一并提交，用户只是改了个错别字，
 *    空着的摘要框却变成了 `""` → 后端存成 null → 摘要被清空。
 *    脏字段的计算在 `buildPatch`，它同时负责把「空字符串」翻译成「清空」。
 *
 * ② **保存之后不停留在编辑器，而是跳到详情页**
 *    因为 slug 可能是**后端生成的**（用户没填时按标题生成、撞车还加序号），
 *    前端在收到响应之前根本不知道这篇文的地址是什么。
 *    留在编辑器里就得编一个「临时地址」的概念，而详情页本来就是
 *    「服务端眼中的结果」的唯一权威展示处。
 */

// 这些上限是后端 schema 的口径（`POST_TITLE_MAX_LEN` 等）在客户端的**镜像**。
// 前端校验只是为了让用户不必等一个来回才知道标题太长；
// 真正的判定权在后端，所以这里只做长度，不做 slug 字符集之类的规则
// （规则一多就会出现「前端放行、后端拒绝」，而用户不知道该信谁）。
const TITLE_MAX = 200
const CONTENT_MAX = 100_000
const SUMMARY_MAX = 500
const SLUG_MAX = 120
const COVER_URL_MAX = 512
const MAX_TAGS = 10

interface Values {
  title: string
  content: string
  summary: string
  slug: string
  cover_url: string
  /** 标签在界面上是一个逗号分隔的输入框，提交时才切成数组 */
  tags: string
}

const EMPTY_VALUES: Values = {
  title: '',
  content: '',
  summary: '',
  slug: '',
  cover_url: '',
  tags: '',
}

type Errors = FieldErrors<keyof Values>

/**
 * 后端 `data.field` → 本地字段名。
 *
 * 只有 `tag_names` 需要翻译（界面上叫 `tags`），其余字段名两端一致。
 * 不做统一的命名转换是一个有意的选择：转换规则一旦存在，
 * 就要为「后端新加的字段」再决定一次它该怎么转，而漏掉的字段
 * 会表现为「错误提示显示了，但挂在了不存在的输入框上」——静默失效。
 */
const FIELD_MAP: Record<string, keyof Values> = {
  title: 'title',
  content: 'content',
  slug: 'slug',
  summary: 'summary',
  cover_url: 'cover_url',
  tag_names: 'tags',
}

/**
 * 逗号（中英文）/ 空白都能分隔标签：从别处粘过来的标签串格式不可控。
 *
 * 这里**不截断**到上限。截断看起来「友好」，实际是把用户的输入悄悄丢掉了一半——
 * 他以为写了 12 个标签，只有 10 个生效，而界面上没有任何迹象。
 * 超限由 `validate` 报错拦住。
 */
function parseTags(raw: string): string[] {
  const seen = new Set<string>()
  const tags: string[] = []
  for (const part of raw.split(/[,，\s]+/)) {
    const name = part.trim()
    // 去重按**原样**比较，不做大小写归一：归一规则在后端（按 slug 判重），
    // 前端再造一套只会出现「前端说重复、后端说不是」的扯皮
    if (!name || seen.has(name)) continue
    seen.add(name)
    tags.push(name)
  }
  return tags
}

function toValues(post: PostDetail): Values {
  return {
    title: post.title,
    content: post.content,
    summary: post.summary ?? '',
    slug: post.slug,
    cover_url: post.cover_url ?? '',
    tags: post.tags.join(', '),
  }
}

function validate(values: Values): Errors {
  const errors: Errors = {}
  if (!values.title) errors.title = '请输入标题'
  else if (values.title.length > TITLE_MAX) errors.title = `标题最多 ${TITLE_MAX} 字`

  if (!values.content.trim()) errors.content = '请输入正文'
  else if (values.content.length > CONTENT_MAX) errors.content = `正文最多 ${CONTENT_MAX} 字`

  if (values.summary.length > SUMMARY_MAX) errors.summary = `摘要最多 ${SUMMARY_MAX} 字`
  if (values.slug.length > SLUG_MAX) errors.slug = `链接最多 ${SLUG_MAX} 字`
  if (values.cover_url.length > COVER_URL_MAX) errors.cover_url = '封面地址过长'
  if (parseTags(values.tags).length > MAX_TAGS) errors.tags = `最多 ${MAX_TAGS} 个标签`
  return errors
}

function toCreateInput(values: Values): CreatePostInput {
  const input: CreatePostInput = {
    title: values.title,
    content: values.content,
  }
  // 空字符串不提交：这段字段是「可选」，空值应该等价于「没写」，
  // 而不是「写了一个空摘要」。后端虽然也会把空串归一成 null，
  // 但少发一个字段就少一条要两边保持一致的规则
  if (values.summary.trim()) input.summary = values.summary.trim()
  if (values.slug.trim()) input.slug = values.slug.trim()
  if (values.cover_url.trim()) input.cover_url = values.cover_url.trim()
  const tags = parseTags(values.tags)
  if (tags.length > 0) input.tag_names = tags
  return input
}

/**
 * 当前值与**服务端已知值**的差集（PATCH 语义）。
 *
 * 空字符串在这里被翻译成 `null`（= 清空），这是本函数和 `toCreateInput` 唯一
 * 不一致的地方，原因也是真的不一致：
 *   新建时「空」= 我不打算设这个值（字段不存在）；
 *   编辑时「空」= 我要把它清掉（字段为 null）。
 *   如果编辑也当成「不存在」，用户就永远清不掉之前写过的摘要。
 */
function buildPatch(baseline: Values, current: Values): UpdatePostInput {
  const patch: UpdatePostInput = {}

  if (current.title !== baseline.title) patch.title = current.title
  if (current.content !== baseline.content) patch.content = current.content
  if (current.summary !== baseline.summary) patch.summary = current.summary.trim() || null
  if (current.cover_url !== baseline.cover_url) {
    patch.cover_url = current.cover_url.trim() || null
  }

  // slug 留空表示「不改」而不是「清空」：永久链接没有空值这个合法状态，
  // 后端收到 null 也会把它丢掉（见端点里的注释）。
  // 所以这里多一个 `&& current.slug.trim()`，把「清空输入框」这个动作
  // 解释成「保持原样」——客户端表单能做出的动作，不一定都是合法状态
  if (current.slug !== baseline.slug && current.slug.trim()) {
    patch.slug = current.slug.trim()
  }

  // 标签是**整体替换**：后端不接受「追加一个标签」这种增量语义，
  // 所以只要文本变了就提交完整列表（清空时提交 `[]`，不是 null：
  // 两者在后端都会清空，但 [] 与「列表」是同一个类型，少一次类型分歧）
  if (current.tags !== baseline.tags) patch.tag_names = parseTags(current.tags)

  return patch
}

export function PostEditorPage() {
  // 路由参数名叫 slug 而不是 postId：它在 URL 里是永久链接，
  // 页面也是靠 `GET /posts/{slug}` 把内容读回来的。
  // 真正用于 PATCH 的是读回来之后的 `post.id`——后端改文章按 id 定位，
  // 因为 slug 是可变的，用它在写路径上定位会在「改 slug 的同时改正文」时
  // 变得很别扭（先改地址再按新地址提交，等于要求客户端知道服务端的执行顺序）
  const { slug } = useParams<{ slug: string }>()
  const isEditing = Boolean(slug)

  const navigate = useNavigate()
  const { user } = useAuth()
  const accessQuery = useMyAccessQuery()

  const postQuery = usePostQuery(slug)
  const createMutation = useCreatePostMutation()
  const updateMutation = useUpdatePostMutation()
  const publishMutation = usePublishPostMutation()

  const [values, setValues] = useState<Values>(EMPTY_VALUES)
  /**
   * 已保存的值。脏字段是与它比较得出的，所以它必须在**每次保存成功后**跟着前移，
   * 否则「保存 → 再改一个字 → 保存」会把上一次已经保存过的内容再提交一遍
   * （虽然结果一样，但会在并发编辑时把别人的改动覆盖回去）。
   */
  const [baseline, setBaseline] = useState<Values>(EMPTY_VALUES)
  /** 已经用哪一篇的数据填过表单。用来保证「加载完成时填充」只发生一次。 */
  const [loadedPostId, setLoadedPostId] = useState<string | null>(null)

  const [fieldErrors, setFieldErrors] = useState<Errors>({})
  const [formError, setFormError] = useState<string | null>(null)
  /** 正在提交的是哪个动作，用来把「保存」和「保存并发布」两个按钮分别置灰 */
  const [submitting, setSubmitting] = useState<'save' | 'publish' | null>(null)
  const [preview, setPreview] = useState(false)

  const post = postQuery.data

  /**
   * 详情加载完成后填充表单——**在渲染期同步**而不是用 useEffect。
   *
   * 用 effect 的话，首次渲染会先画出一张空表单，然后 effect 跑完再画一次带内容的，
   * 用户会看到输入框闪一下（内容从空变成有）。渲染期 setState 由 React 直接
   * 重跑渲染而不提交中间结果，没有这一帧。
   *
   * 条件是「id 变了」而不是「data 变了」：保存之后 hooks 会把新详情写进缓存，
   * 那会让 data 变成新对象；如果据此重填表单，用户正在敲的字会被覆盖掉。
   */
  if (post && post.id !== loadedPostId) {
    const next = toValues(post)
    setLoadedPostId(post.id)
    setValues(next)
    setBaseline(next)
  }

  const setValue = (key: keyof Values) => (value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => withoutFieldError(prev, key))
    setFormError(null)
  }

  const canEdit = post ? canEditPost(accessQuery.data?.permission_codes, post, user?.id) : true
  const isPublished = post?.status === 'published'
  const pending = submitting !== null

  /**
   * 落盘。`publish` 决定保存之后要不要立刻发布。
   *
   * 两步（保存 → 发布）而不是一个后端接口，是因为它们本来就是两件事：
   * 「保存」只改内容，「发布」才决定内容对外可见，而后者的权限码也是独立的
   * （`post:publish`）。前端把两次调用串起来只是省一次点击，
   * 不代表服务端可以把它们合成一个接口——否则将来「先审后发」
   * 要改的就是接口契约，而不只是前端的一个按钮。
   */
  const save = async (publish: boolean): Promise<PostDetail> => {
    if (post) {
      let saved = post
      const patch = buildPatch(baseline, values)
      // 一个字段都没改就不发请求：PATCH 空对象在后端是合法的无操作，
      // 但它仍会走一遍归属校验和一次 UPDATE，白白产生一次「刚刚更新了」的假象
      // （`updated_at` 会变，而内容是旧的）
      if (Object.keys(patch).length > 0) {
        saved = await updateMutation.mutateAsync({ postId: post.id, slug: post.slug, input: patch })
        setBaseline(values)
      }
      if (publish && saved.status !== 'published') {
        saved = await publishMutation.mutateAsync(saved.id)
      }
      return saved
    }

    const created = await createMutation.mutateAsync(toCreateInput(values))
    return publish ? publishMutation.mutateAsync(created.id) : created
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void submit(false)
  }

  const submit = (publish: boolean) => {
    setFormError(null)

    const errors = validate(values)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) {
      // 错误信息挂在输入框下面，但用户可能已经滚到页面底部按了按钮，
      // 所以顶上也给一句，否则「点了没反应」
      setFormError('表单里还有需要修正的地方')
      return
    }

    setSubmitting(publish ? 'publish' : 'save')
    save(publish)
      .then((detail) => {
        // replace：编辑器是从详情页点进来的，保存后不该在历史里留下
        // 「返回 → 又回到一个内容已经过时的编辑器」
        navigate(`/posts/${encodeURIComponent(detail.slug)}`, { replace: true })
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError) {
          const field = error.field ? FIELD_MAP[error.field] : undefined
          if (field) {
            setFieldErrors(withFieldError(field, error.message))
            return
          }
          // 40330（这不是你的文章）/ 40930（slug 被占用，但它带 field 会走上面）
          // 都属于「重试也没用」的错误，直接说清楚比只显示「保存失败」有用
          setFormError(error.message)
          return
        }
        setFormError('保存失败，请稍后重试')
      })
      .finally(() => setSubmitting(null))
  }

  // ──────────────────────────── 渲染前置分支 ────────────────────────────

  if (isEditing && postQuery.isPending) {
    return <p className="text-sm text-gray-500">加载中…</p>
  }

  if (isEditing && (postQuery.error || !post)) {
    const error = postQuery.error
    const isNotFound = error instanceof ApiError && error.code === 40430
    return (
      <div className="flex flex-col gap-4">
        <Alert tone="error">
          {isNotFound
            ? '找不到这篇文章。它可能已被删除，或者不是你写的。'
            : error instanceof ApiError
              ? error.message
              : '无法加载这篇文章'}
        </Alert>
        <Link to="/my/posts" className="text-sm text-brand hover:opacity-70">
          ← 返回我的文章
        </Link>
      </div>
    )
  }

  /**
   * 能读到文章 ≠ 能编辑它。
   *
   * 编辑页的守卫只能保证「有 post:update 这个能力」，而这条路（作者本人）是
   * 「这一篇是不是你的」。中间那一步是读到了才能判定的，所以它只能在这里判。
   * 提前拦住比让用户写完一大段再吃一个 403 好得多。
   */
  if (post && !canEdit) {
    return (
      <div className="flex flex-col gap-4">
        <Alert tone="error">这不是你的文章，你没有编辑它的权限。</Alert>
        <Link
          to={`/posts/${encodeURIComponent(post.slug)}`}
          className="text-sm text-brand hover:opacity-70"
        >
          ← 返回文章
        </Link>
      </div>
    )
  }

  const tagsPreview = parseTags(values.tags)

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-gray-900">
            {isEditing ? '编辑文章' : '写文章'}
          </h1>
          {post && <PostStatusBadge status={post.status} />}
        </div>

        {/* 编辑/预览切换。不并行摆两栏：正文可能很长，
            并排会把每一行都压成难以阅读的窄条 */}
        <div className="flex rounded-lg border border-gray-200 p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setPreview(false)}
            className={`rounded-md px-3 py-1 ${preview ? 'text-gray-500' : 'bg-gray-100 text-gray-900'}`}
          >
            编辑
          </button>
          <button
            type="button"
            onClick={() => setPreview(true)}
            className={`rounded-md px-3 py-1 ${preview ? 'bg-gray-100 text-gray-900' : 'text-gray-500'}`}
          >
            预览
          </button>
        </div>
      </div>

      {formError && <Alert tone="error">{formError}</Alert>}

      <TextField
        id="title"
        label="标题"
        value={values.title}
        onChange={setValue('title')}
        maxLength={TITLE_MAX}
        required
        error={fieldErrors.title}
        placeholder="给这篇文章起个名字"
      />

      {preview ? (
        <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
          {values.content.trim() ? (
            <MarkdownContent content={values.content} />
          ) : (
            <p className="text-sm text-gray-400">还没有正文。</p>
          )}
        </div>
      ) : (
        <TextAreaField
          id="content"
          label="正文（Markdown）"
          value={values.content}
          onChange={setValue('content')}
          rows={20}
          maxLength={CONTENT_MAX}
          error={fieldErrors.content}
          placeholder={'支持 Markdown：## 标题、**粗体**、`代码`、- 列表、> 引用、| 表格 |'}
          hint="切到「预览」可以看渲染结果。"
        />
      )}

      <TextAreaField
        id="summary"
        label="摘要"
        value={values.summary}
        onChange={setValue('summary')}
        rows={3}
        maxLength={SUMMARY_MAX}
        error={fieldErrors.summary}
        placeholder="留空则列表里自动截取正文开头"
        hint="摘要只影响列表页的展示，不参与正文渲染。"
      />

      <TextField
        id="slug"
        label="永久链接"
        value={values.slug}
        onChange={setValue('slug')}
        maxLength={SLUG_MAX}
        error={fieldErrors.slug}
        placeholder={isEditing ? '留空则保持不变' : '留空则由标题自动生成'}
        hint={
          isEditing ? (
            <span className="text-amber-600">改动链接会让已经分享出去的旧地址失效。</span>
          ) : (
            '中文标题会生成拼音之外的短串（由后端按标题归一），撞车时自动加序号。'
          )
        }
      />

      <TextField
        id="cover_url"
        label="封面图地址"
        value={values.cover_url}
        onChange={setValue('cover_url')}
        type="url"
        maxLength={COVER_URL_MAX}
        error={fieldErrors.cover_url}
        placeholder="https://…"
        hint="留空则列表卡片不显示图片。"
      />

      <TextField
        id="tags"
        label="标签"
        value={values.tags}
        onChange={setValue('tags')}
        error={fieldErrors.tags}
        placeholder="后端, 数据库"
        hint={
          tagsPreview.length > 0
            ? `将写入 ${tagsPreview.length} 个标签：${tagsPreview.join(' / ')}`
            : `用逗号分隔，最多 ${MAX_TAGS} 个。不存在的标签会自动创建。`
        }
      />

      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-gray-100 pt-4">
        <Link
          to={post ? `/posts/${encodeURIComponent(post.slug)}` : '/my/posts'}
          className="mr-auto text-sm text-gray-500 hover:text-gray-900"
        >
          取消
        </Link>

        <button
          type="submit"
          disabled={pending}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
        >
          {submitting === 'save' ? '保存中…' : post ? '保存' : '保存草稿'}
        </button>

        {/*
          已发布的文章不给「保存并发布」按钮：那个组合对它来说要么是空操作
          （已经发布了），要么是它**做不到**的事——后端没有 published → draft
          这条迁移，所以「保存并发布」在已发布状态下没有任何一个正确含义。
          想改变可见性请用详情页的「下架」，那是另一个动作、另一个权限。
        */}
        {!isPublished && (
          <button
            type="button"
            disabled={pending}
            onClick={() => submit(true)}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            {submitting === 'publish' ? '发布中…' : '保存并发布'}
          </button>
        )}
      </div>

      {!isPublished && (
        <p className="text-right text-xs text-gray-400">
          保存会留成草稿，只有你自己能看到；发布之后才会出现在公开列表里。
        </p>
      )}
    </form>
  )
}
