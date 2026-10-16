import { TAG_STATUS_LABEL } from './types'

import type { TagStatusValue } from './types'

/**
 * 状态筛选：一排平铺按钮。
 *
 * ── 为什么不是下拉，也没有「全部」这一项 ──
 * ① 平铺而不是下拉：可选项最多三个，全部露出来的点击次数比"展开下拉再选"少一次，
 *    而且当前选中项在收起来的下拉里也要占同样的视觉空间。
 * ② **没有「全部」**：后端的 `GET /tags` 默认 `status=normal`，
 *    而 `TagStatus.parse` 只接受三个具体取值——它**刻意**不接受空串，
 *    理由写在 entities.py 里（`?status=delteed` 这种笔误若被当成"不筛选"，
 *    前端会收到整份列表而且看起来完全正常，问题会被埋到很久以后）。
 *    所以「不筛状态」这个请求**根本表达不出来**，做一个「全部」按钮
 *    只能靠前端发三次请求再合并——为了一个下拉里少一项而把排序、分页
 *    全部弄乱，不值得。真实需求（"我刚下架的那个去哪了"）用单独的 tab 就答完了。
 *
 * ── 为什么这不是"前端私有的枚举" ──
 * `value` 直接就是后端取值，不需要映射表把它翻译成别的东西：
 * 加一层 `all → undefined` 的转换只在需要「全部」时才划算，现在不需要。
 */
export function TagStatusTabs({
  value,
  onChange,
  options,
}: {
  value: TagStatusValue
  onChange: (next: TagStatusValue) => void
  /**
   * 露出哪几档。默认三档全给（管理员要审阅垃圾数据）；
   * 作者维度传 `['normal']` 之外的组合时必须另行想清楚——
   * 作者看得到「已下架」「已删除」的**自己**的标签是合理的（"我的标签去哪了"），
   * 但看不到别人的，因为查询本身已经按 author_id 收窄了。
   */
  options?: readonly TagStatusValue[]
}) {
  const items = options ?? (['normal', 'abnormal', 'deleted'] as const)

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((status) => {
        const active = status === value
        return (
          <button
            key={status}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(status)}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              active
                ? 'border-brand bg-purple-50 text-brand'
                : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
            }`}
          >
            {TAG_STATUS_LABEL[status]}
          </button>
        )
      })}
    </div>
  )
}
