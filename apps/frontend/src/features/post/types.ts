/**
 * blog（文章）相关的响应类型。
 *
 * 这些形状和后端 `app/presentation/api/v1/schemas/post.py` 是**契约**关系：
 * 后端改了字段名，这里必须一起改，否则运行时才会发现
 * （表现为 `post.published_at` 是 undefined，而不是编译错误）。
 *
 * 字段名保持 **snake_case**，不做驼峰转换：
 *   中间加一层「JSON 转驼峰」听起来更符合前端的书写习惯，但它同时引入了一处
 *   「转换规则」需要维护——嵌套对象、数组、`null` 的处理都要重新定义一遍，
 *   而收益只是省下几个下划线。类型定义在这里、用在页面里，
 *   照着后端的字念反而是最不容易错的做法。
 */

/** 文章状态。与后端 `domain/blog/entities.py::PostStatus` 的取值一一对应。 */
export type PostStatus = 'draft' | 'published' | 'archived'

/**
 * 状态的中文名。
 *
 * 写成显式的映射表而不是 `status === 'draft' ? '草稿' : '已发布'`：
 * 后者的 `else` 分支会把 `archived`（已归档）误显示成「已发布」，
 * 而归档正是作者主动下架时最需要说清楚的状态。
 */
export const POST_STATUS_LABEL: Record<PostStatus, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

/** 状态的徽章配色。key 用状态码而不是中文名，理由同 role 徽章：显示名会变，码不会。 */
export const POST_STATUS_BADGE_CLASS: Record<PostStatus, string> = {
  draft: 'bg-gray-50 text-gray-600 border-gray-200',
  published: 'bg-green-50 text-green-700 border-green-200',
  archived: 'bg-amber-50 text-amber-700 border-amber-200',
}

/** 列表项（`PostSummaryResponse`）。 */
export interface PostSummary {
  id: string
  /** 作者的用户 id。后端只给 id 不给名字，列表页据此判断「这篇是不是我写的」。 */
  author_id: string
  title: string
  slug: string
  /** 摘要。为空时由后端在展示侧截取正文，前端不必兜底造一个。 */
  summary: string | null
  cover_url: string | null
  status: string
  /** 首次发布时刻。草稿为 null——这正是「没发过」和「发过又下架」的区别。 */
  published_at: string | null
  view_count: number
  tags: string[]
  created_at: string
  updated_at: string
}

/**
 * 详情（`PostDetailResponse`）。
 *
 * 后端是「摘要字段 + content」的**扁平**对象（不是嵌套），所以这里用继承表达
 * 「详情是摘要的超集」。用继承而不是 `{ summary: PostSummary; content: string }`，
 * 是因为扁平结构下页面可以直接 `post.title`，
 * 而列表页也能原样把一个 `PostDetail` 当 `PostSummary` 传给展示组件。
 */
export interface PostDetail extends PostSummary {
  /** 正文（Markdown 原文，渲染交给 MarkdownContent 组件）。 */
  content: string
}

/**
 * 分页（`PostPageResponse`）。
 *
 * `offset` / `limit` 是**服务端收敛后**的实际值，不是请求里传的那份：
 * 传 limit=1000 会拿回 limit=100，用自己传的值算总页数一定会算错。
 */
export interface PostPage {
  items: PostSummary[]
  total: number
  offset: number
  limit: number
}

/** 新建入参（`CreatePostRequest`）。没有 `status`、没有 `author_id`，两者都由后端定。 */
export interface CreatePostInput {
  title: string
  content: string
  summary?: string
  slug?: string
  cover_url?: string
  tag_names?: string[]
}

/**
 * 编辑入参（`UpdatePostRequest`，PATCH 语义）。
 *
 * ⚠️ **未出现**与**显式 null** 含义不同，这是本文件最需要记住的一件事：
 *   字段不存在 → 后端收到 UNSET → 不改动；
 *   `summary: null` → 后端收到 None → 清空。
 * 因此编辑页提交时必须只放**用户真的改过**的字段（见 `PostEditorPage` 的脏字段计算），
 * 整体 `{...form}` 提交会把没动过的摘要、封面、标签一起清空。
 * 类型上把「可清空」的字段写成 `| null`，就是为了让这件事在代码里显式可见。
 */
export interface UpdatePostInput {
  title?: string
  content?: string
  summary?: string | null
  /** null 会被后端忽略：永久链接没有「清空」这个合法状态。 */
  slug?: string | null
  cover_url?: string | null
  /** 整体替换；传 null 表示清空全部标签。 */
  tag_names?: string[] | null
}

/** 列表查询参数。`tag` 传标签名（后端按标签的 slug 归一后匹配）。 */
export interface PostListParams {
  offset?: number
  limit?: number
  tag?: string
}

/** 「我的文章」查询参数。`status` 不传表示全部（含草稿）。 */
export interface MyPostListParams {
  offset?: number
  limit?: number
  status?: PostStatus
}
