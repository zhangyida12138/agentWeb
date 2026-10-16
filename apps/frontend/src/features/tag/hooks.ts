import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { changeTagStatus, createTag, deleteTag, fetchTags, tagKeys, updateTag } from './api'

import type { CreateTagInput, TagListParams, TagStatusValue, UpdateTagInput } from './types'

/**
 * tag 模块的数据层（TanStack Query 封装）。
 *
 * ── 这里最重要的一条决定：**写操作一律 invalidate，不做手工写缓存** ──
 *
 * `features/post/hooks.ts` 里有 `syncAfterWrite()`，它把写结果直接塞进详情缓存。
 * 那套做法**不能**平移到标签上，原因是标签列表的排序与过滤都由服务端决定：
 *
 *   ① 排序键是 `post_count desc, name asc`。改个名字就可能让这一行
 *      在两个标签之间换位置——手工写缓存得到的是「位置错的正确数据」。
 *   ② 列表是按 `status` 过滤的。把一条标签下架，它必须从「正常」那一页消失；
 *      手工写缓存会让它原地留着，用户以为操作没生效。
 *   ③ `post_count` 根本不在写接口的返回语义里（`add` 路径上恒为 0）——
 *      它只由列表查询的 `outerjoin` 算出来。用写结果覆盖列表行会把计数抹成 0。
 *
 * 反面成本是「改一条之后多一次列表请求」。标签是低频、小批量的管理动作，
 * 这个代价远小于显示错位数据。**能直接写缓存的前提是「写结果 == 列表里那一行」，
 * 而这里前提不成立。**
 */

const LIST_STALE_TIME = 30_000

interface EnabledOption {
  /**
   * 是否发请求。
   *
   * 不是可选的优化项，而是**必须**的：
   * 未登录的游客也会看到标签页（公开阅读区），
   * 而 `GET /tags` 虽然不要求认证，但在"我的标签"这个视图里
   * 我们依赖 `author_id`，没有登录时请求出去只会拿回一份无意义的列表。
   * 传 `false` 从源头掐掉请求，而不是让请求发出去再在 UI 上假装没发生。
   */
  enabled?: boolean
}

/**
 * 标签列表。
 *
 * `placeholderData: keepPreviousData` 是必须的，不是为了"体验更好"，而是为了**正确**：
 *   翻页/换筛选时 `params` 变了，默认行为是 `data` 立刻变 `undefined`，
 *   表格会闪一下空白再出现新内容，同时 `isPending` 为 true ——
 *   页面上「加载中…」和「没有数据」两个分支会先后各闪一次，
 *   看起来像"筛选之后没有结果"。
 */
export function useTagsQuery(params: TagListParams = {}, { enabled = true }: EnabledOption = {}) {
  return useQuery({
    queryKey: tagKeys.lists(params),
    queryFn: () => fetchTags(params),
    enabled,
    staleTime: LIST_STALE_TIME,
    placeholderData: keepPreviousData,
  })
}

/** 失效标签的全部列表：任何一个写操作都会改变排序、过滤结果或计数。 */
function useInvalidateTags() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: tagKeys.root })
}

/**
 * 新建标签（管理员）。
 *
 * 成功后必须失效列表：新标签的 `post_count` 是 0，按
 * 「引用数倒序」排在最后一页，不做失效的话管理员在当前页看不到它，
 * 会以为"创建失败了"然后重复提交一次——第二次拿到的就是
 * 40950（名称或 slug 已存在），一个完全由前端缓存策略制造出来的错误。
 */
export function useCreateTagMutation() {
  const invalidate = useInvalidateTags()
  return useMutation({
    mutationFn: (input: CreateTagInput) => createTag(input),
    onSuccess: invalidate,
  })
}

/**
 * 编辑标签（作者改自己的 / 管理员改任意 user 标签）。
 *
 * 错误**不在这里吞掉**：调用方（弹窗）需要 `ApiError.field` 把
 * "名称已存在" 挂到输入框上、把 40051（系统标签不可改）显示成整表错误。
 * 在 hook 里统一 toast 会把这两种性质完全不同的失败混成一句"操作失败"。
 */
export function useUpdateTagMutation() {
  const invalidate = useInvalidateTags()
  return useMutation({
    mutationFn: ({ tagId, input }: { tagId: string; input: UpdateTagInput }) =>
      updateTag(tagId, input),
    onSuccess: invalidate,
  })
}

/** 改状态（下架 / 恢复）。恢复已删除的标签也走这里。 */
export function useChangeTagStatusMutation() {
  const invalidate = useInvalidateTags()
  return useMutation({
    mutationFn: ({ tagId, status }: { tagId: string; status: TagStatusValue }) =>
      changeTagStatus(tagId, status),
    onSuccess: invalidate,
  })
}

/**
 * 删除标签（软删除，幂等）。
 *
 * 对"已经删掉的标签再删一次"后端返回 204，所以这里不需要
 * "是不是已经删了"的前置判断——界面隐藏按钮是为了别误导用户，
 * 不是为了避免报错。
 */
export function useDeleteTagMutation() {
  const invalidate = useInvalidateTags()
  return useMutation({
    mutationFn: (tagId: string) => deleteTag(tagId),
    onSuccess: invalidate,
  })
}
