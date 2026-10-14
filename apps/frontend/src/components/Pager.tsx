/**
 * 分页控件：上一页 / 下一页 + 页码说明。
 *
 * 抽出来的理由：文章列表、我的文章、用户列表三处需要完全一样的东西，
 * 各写一遍的代价不只是重复，而是**边界判断会各写各的**：
 * 「下一页」什么时候禁用、总页数用什么算，任何一处写错都会表现为
 * 「最后一页还能点下一页，点完列表空了」。
 *
 * 三个数都从**服务端响应**里取（`offset` / `limit` / `total`），不用本地常量：
 *   服务端会把越界的 limit 收敛（传 1000 拿回 100），拿本地传的值算总页数
 *   一定会算多；`total` 变化时也容易出现「页码还停在旧的最后一页」。
 */

interface PagerProps {
  offset: number
  /** 服务端收敛后的每页条数 */
  limit: number
  total: number
  /** 本页实际拿到的条数，用于推导「还有没有下一页」 */
  itemCount: number
  /** 请求进行中：禁用按钮，避免连点造成多次跳页 */
  isFetching?: boolean
  onOffsetChange: (nextOffset: number) => void
}

export function Pager({
  offset,
  limit,
  total,
  itemCount,
  isFetching = false,
  onOffsetChange,
}: PagerProps) {
  if (limit <= 0 || total <= 0) return null

  const pageCount = Math.max(1, Math.ceil(total / limit))
  const page = Math.floor(offset / limit)

  // 用「本页起点 + 本页实际条数 < total」判断，而不是「page + 1 < pageCount」：
  // 后者依赖 total/limit 整除，删除几条后会出现「明明没有下一页了但按钮还亮着」
  const hasNext = offset + itemCount < total

  return (
    <div className="flex items-center justify-end gap-3 text-sm">
      <span className="text-gray-500">
        第 {page + 1} / {pageCount} 页 · 共 {total} 篇
      </span>
      <button
        type="button"
        onClick={() => onOffsetChange(Math.max(0, offset - limit))}
        disabled={offset <= 0 || isFetching}
        className="rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-40"
      >
        上一页
      </button>
      <button
        type="button"
        onClick={() => onOffsetChange(offset + limit)}
        disabled={!hasNext || isFetching}
        className="rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-40"
      >
        下一页
      </button>
    </div>
  )
}
