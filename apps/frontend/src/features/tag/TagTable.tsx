import { canChangeTagStatus, canDeleteTag, canEditTag, canManageTags } from './permissions'
import {
  TAG_STATUS_BADGE_CLASS,
  TAG_STATUS_LABEL,
  TAG_TYPE_BADGE_CLASS,
  TAG_TYPE_LABEL,
} from './types'

import type { Tag, TagStatusValue } from './types'

/**
 * 标签列表表格（两个维度的页面共用）。
 *
 * ── 为什么要共用，而不是各写一张表 ──
 * 「管理员」和「作者」看到的确实是不同的表：
 *   作者只看自己那几行，能做的只有"改名/改描述"；
 *   管理员看全部，能做的还有"下架/恢复/删除"。
 * 但**共用的是「一行标签长什么样」这件事**——名称、slug、描述、
 * 状态徽章的配色与文案。抄两份的后果是：将来给状态加一个取值，
 * 两张表里必然只有一张会更新，另一张会把它显示成空白。
 * 所以共用的是**行与单元格**，而列集合与操作集合由 `variant` 决定——
 * 维度差异集中在一个 prop 上，而不是散在两个文件里。
 *
 * ── 操作按钮的显隐在这里算，不在页面里 ──
 * `canEditTag` 的结论**逐行不同**（系统标签谁都改不了、别人的标签非管理员不能改），
 * 所以判定必须发生在 `tags.map` 里面。把这套判定留在页面里意味着页面要
 * 遍历两次列表（一次算权限、一次渲染），或者把结论塞进一个 Map——
 * 两条路都比"在行内算"难读，而且多一个可能不同步的中间结构。
 */

/** 一行的操作按钮。抽出来只为了让三个按钮的样式不会各自漂移。 */
const ACTION_CLASS = 'text-brand transition-opacity hover:opacity-70 disabled:opacity-40'
const DANGER_ACTION_CLASS = 'text-red-600 transition-opacity hover:opacity-70 disabled:opacity-40'

/**
 * 当前状态下，"改状态"按钮的文案与目标状态。
 *
 * 一条动作承担两个方向：正常→下架、下架/已删除→恢复。
 * **已删除的恢复走的是同一条 `PATCH /status`**（后端刻意不在那条路径上
 * 检查 `ensure_not_deleted`），所以这里不需要为"取消删除"另开一个按钮——
 * 多一个按钮只会让管理员以为它们背后是两套逻辑。
 */
function statusAction(status: string): { label: string; next: TagStatusValue } {
  return status === 'normal'
    ? { label: '下架', next: 'abnormal' }
    : { label: '恢复', next: 'normal' }
}

/**
 * 创建者的展示文案。
 *
 * ⚠️ 有意的**降级**：接口只给 `author_id`（uuid），不给用户名。
 *    为了把 uuid 变成"张三"而多发一次用户列表请求，代价是这张表
 *    在管理员每次翻页时都多一个依赖、多一个加载态、多一个 4xx 的可能。
 *    管理员实际会问的问题是「这条是不是我建的 / 有没有主」，
 *    这两个问题用三种标签就答完了，uuid 放进 `title` 供排查时复制。
 */
function authorLabel(tag: Tag, currentUserId: string | undefined): string {
  if (!tag.author_id) return '无主'
  if (currentUserId && tag.author_id === currentUserId) return '我'
  return '他人'
}

function StatusBadge({ status }: { status: string }) {
  // 后端把 status 当字符串给（不是枚举），所以这里必须容忍未知取值：
  // 直接 `TAG_STATUS_LABEL[status]` 会得到 undefined，页面上就是一个空徽章。
  // 显示原始值比显示空白好——空白让人以为是渲染 bug，原始值至少能搜。
  const known = status in TAG_STATUS_LABEL
  const label = known ? TAG_STATUS_LABEL[status as TagStatusValue] : status
  const tone = known
    ? TAG_STATUS_BADGE_CLASS[status as TagStatusValue]
    : 'bg-gray-50 text-gray-500 border-gray-200'
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${tone}`}>{label}</span>
  )
}

function TypeBadge({ type }: { type: string }) {
  const known = type in TAG_TYPE_LABEL
  const label = known ? TAG_TYPE_LABEL[type as keyof typeof TAG_TYPE_LABEL] : type
  const tone = known
    ? TAG_TYPE_BADGE_CLASS[type as keyof typeof TAG_TYPE_BADGE_CLASS]
    : 'bg-gray-50 text-gray-500 border-gray-200'
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${tone}`}>{label}</span>
  )
}

export interface TagTableProps {
  tags: Tag[]
  codes: readonly string[] | undefined
  currentUserId: string | undefined
  /**
   * 展示维度。
   *   `mine`   —— 作者维度：只看"是不是我的"，不露类型/创建者列，没有治理动作。
   *   `manage` —— 管理员维度：露出类型与创建者列，带下架/恢复/删除。
   */
  variant: 'mine' | 'manage'
  onEdit: (tag: Tag) => void
  onToggleStatus: (tag: Tag) => void
  onDelete: (tag: Tag) => void
  /**
   * 正在处理的那一行的 id（否则 null）。
   *
   * 只禁用**这一行**的按钮，而不是给整张表盖一层遮罩：
   * 管理员常做的动作是「连续下架几个垃圾标签」，一行在请求中就锁住整张表
   * 会让后几次点击被静默丢掉。用 id 而不是布尔值，是因为布尔值表达不了"是哪一行"。
   */
  pendingTagId: string | null
}

export function TagTable({
  tags,
  codes,
  currentUserId,
  variant,
  onEdit,
  onToggleStatus,
  onDelete,
  pendingTagId,
}: TagTableProps) {
  const isManage = variant === 'manage'
  // 表格级的能力：与"哪一行"无关的那些。行级能力在每个 map 里现算。
  const showStatusActions = isManage && canChangeTagStatus(codes)
  const canManage = canManageTags(codes)

  return (
    <div className="overflow-x-auto no-scrollbar rounded-2xl border border-gray-100 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500">
            <th className="px-4 py-3 font-medium">标签</th>
            <th className="px-4 py-3 font-medium">状态</th>
            {isManage && <th className="px-4 py-3 font-medium">类型</th>}
            {isManage && <th className="px-4 py-3 font-medium">创建者</th>}
            <th className="px-4 py-3 text-right font-medium">文章数</th>
            <th className="px-4 py-3 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {tags.map((tag) => {
            const editable = canEditTag(codes, tag, currentUserId)
            const deletable = canDeleteTag(codes, tag)
            const toggle = statusAction(tag.status)
            const pending = pendingTagId === tag.id

            return (
              <tr key={tag.id} className="border-t border-gray-100 align-top">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{tag.name}</div>
                  <div className="mt-0.5 text-xs text-gray-400">/{tag.slug}</div>
                  {tag.description && (
                    <div className="mt-1 max-w-md text-xs text-gray-500">{tag.description}</div>
                  )}
                </td>

                <td className="px-4 py-3">
                  <StatusBadge status={tag.status} />
                </td>

                {isManage && (
                  <td className="px-4 py-3">
                    <TypeBadge type={tag.type} />
                  </td>
                )}

                {isManage && (
                  <td className="px-4 py-3 text-gray-600">
                    {/* uuid 只放进 title：它对人没用，但排查"这条是谁建的"时要能复制出来 */}
                    <span title={tag.author_id ?? '没有创建者（存量数据或创建者已注销）'}>
                      {authorLabel(tag, currentUserId)}
                    </span>
                  </td>
                )}

                <td className="px-4 py-3 text-right text-gray-600">{tag.post_count}</td>

                <td className="px-4 py-3">
                  <div className="flex justify-end gap-3">
                    {editable && (
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => onEdit(tag)}
                        className={ACTION_CLASS}
                      >
                        编辑
                      </button>
                    )}

                    {showStatusActions && (
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => onToggleStatus(tag)}
                        className={ACTION_CLASS}
                      >
                        {toggle.label}
                      </button>
                    )}

                    {isManage && deletable && (
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => onDelete(tag)}
                        className={DANGER_ACTION_CLASS}
                      >
                        删除
                      </button>
                    )}

                    {/*
                      三个按钮全不显示时留一个短横，而不是空着：
                      表格里"空白"和"加载失败"看起来一样，而这里空白的含义
                      是确定的——"你没有能对它做的事"（例如已删除的标签
                      对非管理员）。写出来，用户不会以为界面坏了。

                      `canManage` 在这里只用来决定要不要把这句话说完整：
                      管理员看空白行会困惑（"我不是能管吗"），
                      普通作者看到的是他自己建的标签，本来就只有编辑一项。
                    */}
                    {!editable && !showStatusActions && !deletable && (
                      <span className="text-gray-300" title={canManage ? '已删除，无可用操作' : ''}>
                        —
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
