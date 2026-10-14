import { request } from '../../lib/api'

import type {
  CreatePostInput,
  MyPostListParams,
  PostDetail,
  PostListParams,
  PostPage,
  UpdatePostInput,
} from './types'

/**
 * blog 模块的接口封装。
 *
 * 只负责「拼路径、定类型」，不做缓存（那是 hooks 的事），
 * 也不做权限判断（那是 permissions + 页面的事）。
 *
 * 有一处和后端约好的细节值得写在这里：所有写接口返回的都是**完整详情**
 * （新建 201 + 详情、编辑 200 + 详情、发布/下架 200 + 详情），
 * 只有删除是 204。所以除了删除，每次写操作都能直接拿结果去更新缓存，
 * 不需要再补一次 GET——而补的那次 GET 可能读到别的请求造成的中间态。
 */

/**
 * 分页参数 → querystring。
 *
 * `undefined` 的参数会被 URLSearchParams **丢掉**，这正是我们要的语义：
 * 不传 status 表示「不筛状态」，而不是 `status=undefined` 这种字符串。
 * 所以下面各处只写 `params.set(key, value)` 而不判空——
 * 判空交给这个函数一处处理，避免每个调用点各写一遍。
 */
function toQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

/** 公开文章列表（无需登录）。`tag` 传标签名。 */
export function fetchPosts({ offset, limit, tag }: PostListParams = {}): Promise<PostPage> {
  return request<PostPage>(`/posts${toQuery({ offset, limit, tag })}`)
}

/**
 * 按 slug 读单篇文章。
 *
 * 公开接口，但**会带上 token**（`request` 自动注入）：
 * 后端据此判断调用者是不是作者本人，是则允许预览自己的草稿。
 * 所以游客拿到的 404 和作者拿到的 200 走的是同一个 URL。
 */
export function fetchPost(slug: string): Promise<PostDetail> {
  // slug 可能含中文，必须 encode；直接拼进路径会让某些代理/网关解析异常
  return request<PostDetail>(`/posts/${encodeURIComponent(slug)}`)
}

/**
 * 「我的文章」列表（含草稿与已归档）。
 *
 * ⚠️ 路径是 `/me/posts` 而**不是** `/posts/mine`：后者与 `/posts/{slug}`
 * 是同一个模板，slug 恰好叫 `mine` 的文章会永远打不开（见后端 endpoints/posts.py）。
 * 前端路由上的 `/my/posts` 与这个接口路径不同名，改动时不要顺手对齐——
 * 一个是对外 URL 契约，一个是内部路由，没有必须一致的理由。
 */
export function fetchMyPosts({ offset, limit, status }: MyPostListParams = {}): Promise<PostPage> {
  return request<PostPage>(`/me/posts${toQuery({ offset, limit, status })}`)
}

/** 新建文章。总是以草稿落地——后端不接受 status，前端也不该假设能直接发出去。 */
export function createPost(input: CreatePostInput): Promise<PostDetail> {
  return request<PostDetail>('/posts', { method: 'POST', body: input })
}

/**
 * 局部更新文章。
 *
 * `input` 里**只放用户真的改过的字段**：未出现的字段后端当作「不改」，
 * 显式 null 当作「清空」。整体提交表单会把没动过的摘要/封面/标签一起清掉。
 */
export function updatePost(postId: string, input: UpdatePostInput): Promise<PostDetail> {
  return request<PostDetail>(`/posts/${postId}`, { method: 'PATCH', body: input })
}

/** 发布（draft → published，幂等）。 */
export function publishPost(postId: string): Promise<PostDetail> {
  return request<PostDetail>(`/posts/${postId}/publish`, { method: 'POST' })
}

/** 下架（published → archived；重复下架后端回 40035）。 */
export function unpublishPost(postId: string): Promise<PostDetail> {
  return request<PostDetail>(`/posts/${postId}/unpublish`, { method: 'POST' })
}

/**
 * 软删除。后端回 204，所以这里返回 `Promise<void>`。
 *
 * 软删除之后 slug 仍然被占用（唯一索引不认 deleted_at），
 * 于是「删了再发一篇同标题的」会拿到带序号的 slug 而不是复活旧链接——
 * 对已经有外链的旧地址来说这是更安全的行为，页面上不必提示这件事。
 */
export function deletePost(postId: string): Promise<void> {
  return request<void>(`/posts/${postId}`, { method: 'DELETE' })
}

/**
 * queryKey 工厂。
 *
 * 分成 `publicRoot` / `myRoot` 两棵树，是因为它们的失效范围完全不同：
 *   发布/下架/删除既改变公开列表也改变我的列表（一处要跨树失效）；
 *   而编辑标题只影响「我的」（公开列表要等发布后才变）。
 * 前缀分开后，「失效哪一半」在调用点一眼可读，不必去猜某个具体 key 的形状。
 */
export const postKeys = {
  publicRoot: ['post', 'public'] as const,
  myRoot: ['post', 'mine'] as const,
  detailRoot: ['post', 'detail'] as const,

  publicList: (params: PostListParams) =>
    [...postKeys.publicRoot, params.offset ?? 0, params.limit ?? 0, params.tag ?? null] as const,
  myList: (params: MyPostListParams) =>
    [...postKeys.myRoot, params.offset ?? 0, params.limit ?? 0, params.status ?? null] as const,
  /**
   * 详情按 slug 缓存（不是按 id）。
   *
   * 因为读详情的入口只有 slug（路由参数就是它），按 id 缓存会需要一个
   * 「id → slug」的反查才能命中，而那正是我们不想维护的映射。
   * 代价是改 slug 之后旧 slug 的缓存条目会留着，靠失效整棵 detailRoot 解决。
   */
  detail: (slug: string) => [...postKeys.detailRoot, slug] as const,
}
