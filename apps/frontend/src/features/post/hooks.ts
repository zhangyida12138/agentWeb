import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createPost,
  deletePost,
  fetchMyPosts,
  fetchPost,
  fetchPosts,
  postKeys,
  publishPost,
  unpublishPost,
  updatePost,
} from './api'

import type { MyPostListParams, PostDetail, PostListParams, UpdatePostInput } from './types'

/**
 * blog 模块的数据钩子。
 *
 * 缓存策略集中在这里，页面只读 `data` / `isPending` / `error`：
 *   公开列表和详情用较短的 staleTime（30 秒）——文章是别人也在改的内容，
 *   缓存太久会让「刚发的文看不到」变成一个需要刷新才能解释的现象；
 *   但也不能是 0，否则每次从详情返回列表都会重新拉一遍，页面会闪。
 *
 * 所有写操作遵循同一条规矩：**能拿结果就直接写缓存，拿不到才失效**。
 *   后端的写接口都回完整详情（只有删除回 204），所以写缓存这条路总是通的；
 *   缓存一到手，页面上的标题、slug、状态就立刻是新的，不需要等一次额外的 GET，
 *   也就不会出现「保存成功但页面上还是旧标题」的中间态。
 */

/** 公开文章列表（无需登录）。 */
export function usePostsQuery(params: PostListParams = {}) {
  return useQuery({
    queryKey: postKeys.publicList(params),
    queryFn: () => fetchPosts(params),
    staleTime: 30 * 1000,
    // 翻页/换标签时先显示上一份数据，列表不会在切换瞬间塌成空白再长出来
    placeholderData: keepPreviousData,
  })
}

/**
 * 文章详情。
 *
 * `enabled: Boolean(slug)` 是必需的：`useParams()` 在路由还没匹配上时返回空对象，
 * 不拦住的话会先发一次 `GET /posts/`（路径末尾带斜杠）——那其实是列表接口，
 * 拿回一个分页对象去当详情用，页面会以「没有 title」的方式诡异地崩掉。
 */
export function usePostQuery(slug: string | undefined) {
  return useQuery({
    queryKey: postKeys.detail(slug ?? ''),
    queryFn: () => fetchPost(slug as string),
    enabled: Boolean(slug),
    staleTime: 30 * 1000,
  })
}

/**
 * 「我的文章」（含草稿与归档）。
 *
 * `enabled` 由调用方按登录态控制：这个接口要求认证，未登录时必然 401，
 * 而 401 会在 api 层清掉登录态——让一次注定失败的请求去动用户的登录状态，
 * 是那种「刷新首页莫名其妙被登出」的经典来源。
 */
export function useMyPostsQuery(
  params: MyPostListParams = {},
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: postKeys.myList(params),
    queryFn: () => fetchMyPosts(params),
    enabled: options.enabled ?? true,
    // 「我的文章」不设 staleTime（默认 0）：这个列表是作者的工作台，
    // 每次进来都应该是新的，命中旧缓存会让人怀疑「我刚发的草稿去哪了」
    placeholderData: keepPreviousData,
  })
}

/**
 * 把一份详情写进缓存，并同步好「列表可能已经过时」这件事。
 *
 * 单独抽出来是因为四个写操作（新建/编辑/发布/下架）成功后的收尾动作一模一样，
 * 分散写四遍一定会漏掉其中某个失效。
 *
 * 为什么要失效公开列表而不是就地改它：
 *   新建草稿根本不在公开列表里、发布会让一篇文**插入**到列表中间、
 *   下架要把它**移除**——列表的顺序（published_at 倒序）与 total 都会变。
 *   就地改一个分页数组等于在前端重新实现一遍排序与分页，迟早和后端不一致。
 *   文章列表是低频页面，多一次 GET 完全值得。
 */
function syncAfterWrite(
  queryClient: ReturnType<typeof useQueryClient>,
  detail: PostDetail,
  previousSlug?: string,
): void {
  queryClient.setQueryData(postKeys.detail(detail.slug), detail)

  // slug 变了（用户在编辑器里改过永久链接）：旧地址的缓存必须删掉，
  // 否则返回旧 URL 会命中缓存拿到内容，看着像「改 slug 没生效」。
  // 这里用 remove 而不是 invalidate：那条 URL 对应的文章已经不存在了，
  // 失效会让它重新请求一次必然 404 的详情。
  if (previousSlug && previousSlug !== detail.slug) {
    queryClient.removeQueries({ queryKey: postKeys.detail(previousSlug) })
  }

  void queryClient.invalidateQueries({ queryKey: postKeys.publicRoot })
  void queryClient.invalidateQueries({ queryKey: postKeys.myRoot })
}

/** 新建文章。成功后返回的详情直接进缓存，编辑器可以立刻从「新建」切成「编辑」。 */
export function useCreatePostMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createPost,
    onSuccess: (detail) => syncAfterWrite(queryClient, detail),
  })
}

/**
 * 编辑文章。
 *
 * `slug` 是**这篇文当前的** slug（不是要改成的那个），用来在保存后清理旧地址的缓存。
 * `input` 必须只包含用户真的改过的字段，见 `types.ts::UpdatePostInput` 的说明。
 */
export function useUpdatePostMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      postId,
      input,
    }: {
      postId: string
      /** 这篇文当前的 slug，仅用于收尾时清理旧缓存 */
      slug: string
      input: UpdatePostInput
    }) => updatePost(postId, input),
    onSuccess: (detail, variables) => syncAfterWrite(queryClient, detail, variables.slug),
  })
}

/**
 * 发布 / 下架。
 *
 * 两个动作的收尾完全一样（都是「详情更新 + 两个列表失效」），所以共用实现、
 * 只是 `mutationFn` 不同。刻意不合并成一个带 `action` 参数的 mutation：
 * 调用点写成 `publish.mutate(...)` 比 `mutate({action: 'publish'})` 更难写错，
 * 而「下架写成了发布」这种错是要靠外链失效才能发现的。
 */
function useChangeStatusMutation(mutationFn: (postId: string) => Promise<PostDetail>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (detail) => syncAfterWrite(queryClient, detail),
  })
}

export function usePublishPostMutation() {
  return useChangeStatusMutation(publishPost)
}

export function useUnpublishPostMutation() {
  return useChangeStatusMutation(unpublishPost)
}

/**
 * 删除（软删除）。
 *
 * 收尾与其他写操作不同：没有返回的详情可以写缓存，只有 204。
 * 所以要手动清掉那一篇的详情缓存——不清的话，用户删完点浏览器「后退」，
 * 页面会命中缓存把刚删掉的文章原样渲染出来（后端已经 404 了，
 * 但缓存不知道），看起来像删除没生效。
 */
export function useDeletePostMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ postId }: { postId: string; slug: string }) => deletePost(postId),
    onSuccess: (_result, variables) => {
      queryClient.removeQueries({ queryKey: postKeys.detail(variables.slug) })
      void queryClient.invalidateQueries({ queryKey: postKeys.publicRoot })
      void queryClient.invalidateQueries({ queryKey: postKeys.myRoot })
    },
  })
}
