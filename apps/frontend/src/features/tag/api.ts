import { request } from '../../lib/api'

import type {
  CreateTagInput,
  Tag,
  TagListParams,
  TagPage,
  TagStatusValue,
  UpdateTagInput,
} from './types'

/**
 * tag 模块的 HTTP 层。
 *
 * 这一层只做三件事：拼路径、拼查询串、声明出参类型。
 * **不判断权限、不做业务校验**——那些分别在 permissions.ts / 值对象校验里，
 * 而权限的最终裁决点是后端路由守卫（`require_permission(TAG_MANAGE)`）。
 * 混进来会让「前端为什么拦住我」变得没有单一答案。
 */

const TAGS_ROOT = '/tags'

/**
 * 把参数拼成查询串。
 *
 * 丢掉 `undefined` **和空串**：
 *   空串在后端会被当成"确实是空值"，而不是"没传"。
 *   最有代表性的是 `keyword`——传 `?keyword=` 后端会把只含空白的值视为不筛选，
 *   但 `?status=` 会直接被 `TagStatus.parse("")` 判为非法、回 40051。
 *   所以"不筛"的唯一正确表达就是**不带这个参数**，两边对这个语义的理解必须一致。
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

/** 列出标签。默认只返回 `normal`（后端定的），要审阅垃圾数据必须显式传 status。 */
export function fetchTags(params: TagListParams = {}): Promise<TagPage> {
  return request<TagPage>(
    `${TAGS_ROOT}${toQuery({
      offset: params.offset,
      limit: params.limit,
      status: params.status,
      type: params.type,
      keyword: params.keyword,
      // 注意这里是 snake_case：后端 Query 参数就叫 author_id，别名是给小写字母用的
      author_id: params.authorId,
    })}`,
  )
}

/**
 * 新建标签。
 *
 * 这**不是**任何人都能调的接口：路由上挂着 `tag:manage`，
 * 只有管理员能通过。作者拿到标签归属的方式是「写文章时用到了一个新名字」，
 * 走的是文章那条链路。
 */
export function createTag(input: CreateTagInput): Promise<Tag> {
  return request<Tag>(TAGS_ROOT, {
    method: 'POST',
    body: { name: input.name, description: input.description, type: input.type },
  })
}

/**
 * 编辑标签的名称与描述（PUT，整份表示一起提交）。
 *
 * 这是**唯一一条没有权限守卫的写接口**，判定完全发生在用例内部：
 *   `tag:manage` 持有者可以改任何 user 标签，其他人只能改 `author_id === 自己` 的。
 * 接口形态上的后果：前端不能靠"有没有 edit 按钮"来推断权限，
 * 因为同一个人对不同行的结论不同——判定必须以**行**为单位。
 *
 * ⚠️ `description` 传 `null` 表示**清空**（PUT 语义：没提到的就是没有）。
 *    想保留就把它原样带回来，不能省略。
 */
export function updateTag(tagId: string, input: UpdateTagInput): Promise<Tag> {
  return request<Tag>(`${TAGS_ROOT}/${encodeURIComponent(tagId)}`, {
    method: 'PUT',
    body: { name: input.name, description: input.description },
  })
}

/**
 * 改标签状态（下架 / 恢复）。
 *
 * 一条接口承担两个方向的语义，靠 `status` 参数决定，这是有意的：
 *   **恢复已删除的标签也走这里**。所以它拒绝把"恢复"实现成另一个 endpoint——
 *   那会变成同一种资源变更有两个入口，其中一个必然先腐烂。
 *
 * 它**不检查"是否已删除"**（`Tag.ensure_not_deleted` 刻意不在这条路径上调用），
 * 因为「已删除 → 恢复」正是它要支持的场景。前端因此在「已删除」那一行
 * 显示的是「恢复」而不是「删除」。
 */
export function changeTagStatus(tagId: string, status: TagStatusValue): Promise<Tag> {
  return request<Tag>(`${TAGS_ROOT}/${encodeURIComponent(tagId)}/status`, {
    method: 'PATCH',
    body: { status },
  })
}

/**
 * 删除标签（软删除，幂等）。
 *
 * 返回 `void` 而不是被删对象：后端回 204，没有 body。
 * 声明成 `Promise<Tag>` 会在运行时拿到 `null`（`lib/api.ts` 对 204 就是这么处理的），
 * 然后在 `result.status` 上崩掉——一个类型签名撒谎导致的运行时错误。
 */
export function deleteTag(tagId: string): Promise<void> {
  return request<void>(`${TAGS_ROOT}/${encodeURIComponent(tagId)}`, { method: 'DELETE' })
}

/**
 * 查询键工厂。
 *
 * 只留 `root` 与 `lists`：
 *   本项目**没有**标签详情页（点标签跳的是 `GET /posts?tag=<slug>`，走的是 post 的键），
 *   所以 `tagKeys.detail(id)` 今天没有消费者。提前加一个没人用的键，
 *   下次有人看到它就会以为「存在一个详情缓存」，然后在失效时漏掉它。
 */
export const tagKeys = {
  root: ['tag'] as const,
  lists: (params: TagListParams = {}) => ['tag', 'list', params] as const,
}
