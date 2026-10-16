/**
 * tag（标签）相关的类型与展示常量。
 *
 * 这些形状和后端 `app/presentation/api/v1/schemas/tag.py` 是**契约**关系：
 * 后端改了字段名，这里必须一起改，否则运行时才会发现
 * （表现为 `tag.post_count` 是 undefined，而不是编译错误）。
 *
 * 字段名保持 **snake_case**，理由与 `features/post/types.ts` 相同：
 * 中间加一层「JSON 转驼峰」要额外定义一套转换规则（嵌套、数组、null），
 * 收益只是省下几个下划线。
 */

/** 标签状态。与后端 `domain/tag/entities.py::TagStatus` 一一对应。 */
export type TagStatusValue = 'normal' | 'abnormal' | 'deleted'

/** 标签类型。与后端 `domain/tag/entities.py::TagType` 一一对应。 */
export type TagTypeValue = 'system' | 'user'

/**
 * 状态的中文名。
 *
 * 写成显式映射表而不是 `status === 'normal' ? ... : ...`：
 * 后者的 else 分支会把 `abnormal`（已下架）误显示成别的状态，
 * 而「已下架」恰恰是管理员最需要一眼认出来的状态——
 * 它意味着这个标签不再出现在联想与公开列表里，但历史文章上还挂着。
 */
export const TAG_STATUS_LABEL: Record<TagStatusValue, string> = {
  normal: '正常',
  abnormal: '已下架',
  deleted: '已删除',
}

/** 状态徽章配色。key 用状态码而不是中文名：显示名会变，码不会。 */
export const TAG_STATUS_BADGE_CLASS: Record<TagStatusValue, string> = {
  normal: 'bg-green-50 text-green-700 border-green-200',
  abnormal: 'bg-amber-50 text-amber-700 border-amber-200',
  deleted: 'bg-gray-100 text-gray-500 border-gray-200',
}

/**
 * 类型的中文名。
 *
 * `system` 叫「官方」而不是「系统」：这个徽章是给**读者/作者**看的，
 * 它要传达的信息是「这个标签是平台定的，你改不了」，而不是「它是 system 类型」。
 */
export const TAG_TYPE_LABEL: Record<TagTypeValue, string> = {
  system: '官方',
  user: '用户',
}

export const TAG_TYPE_BADGE_CLASS: Record<TagTypeValue, string> = {
  system: 'bg-purple-50 text-purple-700 border-purple-200',
  user: 'bg-white text-gray-500 border-gray-200',
}

/**
 * 名称与描述的长度上限。
 *
 * ⚠️ 这是**契约**，不是前端的产品决定：
 *    后端 `domain/blog/value_objects.py::TAG_NAME_MAX_LEN` = 50、
 *    `domain/tag/value_objects.py::TAG_DESCRIPTION_MAX_LEN` = 100，
 *    由 `presentation/api/v1/schemas/tag.py` 拿去当 Pydantic 的 `max_length`。
 *    前端抄这两个数字，是为了让用户**在输入时**就看到「50/50」而不是
 *    提交后才收到 40000。改了后端必须同步改这里，否则表现为
 *    「前端放行、后端拒绝」——一个只在边界输入下才出现的失败。
 */
export const TAG_NAME_MAX_LEN = 50
export const TAG_DESCRIPTION_MAX_LEN = 100

/**
 * 标签名的形状，与后端 `domain/blog/value_objects.py::_TAG_RE` **逐字对齐**。
 *
 * 拆开看，它同时排除了三件事：
 *   `/` `\` —— 路径分隔符；`#` `?` —— URL 的片段/查询起始符；`%` —— 百分号编码起始符。
 *             标签会出现在 `GET /posts?tag=<slug>` 里，这五个字符会让链接在某一环被解析成别的东西。
 *   `\s`     —— 任何空白。**包括首尾空格和连续多个空格**：
 *             `"a  b"` 与 `"a b"` 归化出的 slug 相同，允许它们在库里共存
 *             会让"按 slug 查"这件事变得有歧义。
 *
 * 前端做这份校验不是为了安全（安全在后端值对象里，它才是唯一的执行者），
 * 而是为了让用户在输入时就看见问题，而不是提交一轮之后才收到 40036。
 * 两边的正则**必须逐字一致**——不一致的后果是「前端放行、后端拒绝」，
 * 一个只在边界输入下才出现的失败，而且失败的那一条路径上没有任何提示。
 *
 * 字符类里的 `\\` 是**必须**的双写（单写会被当成转义下一个字符），
 * 所以这里不需要 `no-useless-escape` 的豁免。
 */
export const TAG_NAME_RE = /^[^\s/\\#?%]+(?: [^\s/\\#?%]+)*$/

/**
 * 校验标签名，返回错误文案或 null。
 *
 * 返回**文案**而不是布尔值，是为了让调用方（表单）不必再写一遍
 * 「为什么不行」——三种失败的原因完全不同，用户看到的也该是三句不同的话。
 */
export function tagNameError(name: string): string | null {
  const trimmed = name.trim()
  if (!trimmed) return '标签名不能为空'
  if (trimmed.length > TAG_NAME_MAX_LEN) return `标签名最多 ${TAG_NAME_MAX_LEN} 位字符`
  if (!TAG_NAME_RE.test(trimmed)) return '标签名不能包含 / \\ # ? %，也不能有连续空格'
  return null
}

/**
 * 校验标签描述。空描述**不是错误**——它表示"不要描述"，提交时转成 `null` 即可。
 * 所以这里只查长度，不查空。
 */
export function tagDescriptionError(description: string): string | null {
  if (description.trim().length > TAG_DESCRIPTION_MAX_LEN) {
    return `标签描述最多 ${TAG_DESCRIPTION_MAX_LEN} 字`
  }
  return null
}

/**
 * 后端校验错误里的 `field` 值 → 表单字段名。
 *
 * ⚠️ 必须做这个映射，不能直接拿 `ApiError.field` 去索引表单字段，
 *    因为后端同一个"名字"的问题会给出**两个不同的 field**：
 *      · 名字格式非法（空 / 超长 / 含 `#`）→ `40036`，`field = "tag_names"`
 *        —— 这个异常来自 blog 领域的 `TagName` 值对象，它当初是为
 *           「文章表单里的标签数组」设计的，复数形式是那时候的遗留。
 *      · 名字撞车（name 或 slug 已被占用）→ `40950`，`field = "name"`
 *        —— 这个来自 tag 领域自己的 `TagAlreadyExistsError`。
 *    前端只按 `"name"` 匹配的话，**格式错误会掉进"整表错误"分支**，
 *    用户看到的是顶部一句提示，输入框却毫无标记。
 */
export function toFormField(field: string | undefined): 'name' | 'description' | undefined {
  if (field === 'name' || field === 'tag_names') return 'name'
  if (field === 'description') return 'description'
  return undefined
}

/** 标签（`TagResponse`）。 */
export interface Tag {
  id: string
  name: string
  /** 网址部分，由 name 派生。`GET /posts?tag=<slug>` 用它筛选。 */
  slug: string
  description: string | null
  status: string
  type: string
  /**
   * 创建者 id。**可以为 null**，且这个 null 有意义：
   * 表示「这个标签没有归属」——存量数据，或创建者账号已注销
   * （外键 `ON DELETE SET NULL`）。界面应当据此隐藏「编辑」按钮，
   * 而不是把它当成一个名字叫 null 的用户。
   */
  author_id: string | null
  /** 使用该标签的**已发布**文章数。后端算出来的，表里没有这一列。 */
  post_count: number
}

/**
 * 标签分页。
 *
 * `offset` / `limit` 是**服务端收敛后**的实际值，不是请求里传的那份：
 * 传 limit=1000 会拿回 limit=100，用自己传的值算总页数一定会算错。
 */
export interface TagPage {
  items: Tag[]
  total: number
  offset: number
  limit: number
}

/** 列表查询参数。`undefined` 表示不筛（会被 querystring 构造器直接丢掉）。 */
export interface TagListParams {
  offset?: number
  limit?: number
  /**
   * ⚠️ **没有「全部状态」这一档**。
   *    后端 `GET /tags` 的默认值是 `normal`，且 `TagStatus.parse` 只认三个具体取值——
   *    它刻意不接受空串（那是笔误会静默变成「不筛选」，前端的 bug 会被埋很久）。
   *    所以界面上的状态筛选是三个互斥的 tab，而不是「全部 + 三类」的下拉。
   */
  status?: TagStatusValue
  type?: TagTypeValue
  keyword?: string
  /** 只看某个作者创建的标签。作者维度的页面用它把范围收窄到自己身上。 */
  authorId?: string
}

/** 新建标签入参。**没有 author_id**——创建者由后端从 token 推导。 */
export interface CreateTagInput {
  name: string
  description: string | null
  /** `system` 只有管理员能传（路由上挂着 `tag:manage`）。 */
  type: TagTypeValue
}

/** 编辑标签入参（PUT：整份表示一起提交）。 */
export interface UpdateTagInput {
  name: string
  description: string | null
}
