import { POST_STATUS_BADGE_CLASS, POST_STATUS_LABEL } from './types'

import type { PostStatus } from './types'

/**
 * 文章状态徽章。
 *
 * 单独一个组件而不是页内函数：列表页、我的文章、编辑器页头三处都要显示状态，
 * 而「未知状态怎么显示」这个分支必须只有一份实现——
 * 后端将来加一个状态（比如 `reviewing`）时，这里能整体兜底成灰底原文，
 * 而不是三处各显示成空白、各自看起来像 bug。
 */
const DEFAULT_CLASS = 'bg-gray-50 text-gray-600 border-gray-200'

/** 后端返回的 status 是 `string`（不是联合类型），所以要显式窄化一次。 */
function isKnownStatus(status: string): status is PostStatus {
  return status === 'draft' || status === 'published' || status === 'archived'
}

export function PostStatusBadge({ status }: { status: string }) {
  const label = isKnownStatus(status) ? POST_STATUS_LABEL[status] : status
  const className = isKnownStatus(status) ? POST_STATUS_BADGE_CLASS[status] : DEFAULT_CLASS

  return <span className={`rounded-full border px-2 py-0.5 text-xs ${className}`}>{label}</span>
}
