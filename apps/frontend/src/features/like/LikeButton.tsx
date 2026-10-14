/**
 * 点赞按钮（纯展示 + 反馈，不持有数据）。
 *
 * 为什么是**受控**组件（`liked` / `likeCount` 从外面传进来），而不是自己发请求、
 * 自己存状态：
 *   同一个按钮要出现在两个完全不同的数据源上——
 *     文章的赞数来自 `GET /posts/{id}/interactions`；
 *     评论的赞数来自评论列表响应里的每个节点。
 *   如果按钮自己管状态，这两处就得各写一个按钮，且各写一遍「乐观更新 / 回滚」。
 *   拆成「按钮只管画、数据由调用方给」之后，两处共用同一个按钮，
 *   而各自的缓存写回逻辑待在各自的 hooks 里（见 features/like/hooks.ts
 *   与 features/comment/hooks.ts）。
 *
 * `aria-pressed` 而不是 `aria-label` 来暴露状态：
 *   点赞是一个**开关**（toggle button），`aria-pressed` 正是这个语义的标准表达，
 *   屏幕阅读器会读成「已按下 / 未按下」。用 aria-label 拼中文「已点赞」
 *   只是让人读到了同样的字，语义没有传达出去，测试断言也会变成
 *   「断言某段文案」而不是「断言这个开关是开的」。
 *
 * 为什么不用 emoji 当图标：emoji 在不同平台的渲染差异很大（有的彩色有的单色，
 * 字号也压不住），而这个按钮旁边就有数字，字形稍微差一点整行就会歪。
 * 用 ♥ / ♡ 文本字符，颜色和字号完全由 CSS 控制。
 */

interface LikeButtonProps {
  liked: boolean
  likeCount: number
  onToggle: () => void
  /** 请求进行中：禁用并降透明度，避免连点发出两个方向相反的请求。 */
  isPending?: boolean
  /** 不可点（未登录、无权限、文章已下架）。**不要**用它来表达「加载中」。 */
  disabled?: boolean
  /** 不可点的原因。会拼进无障碍名称，并在 title 里给鼠标用户看。 */
  disabledReason?: string
  /** 额外样式，用于评论里的紧凑尺寸。 */
  className?: string
}

export function LikeButton({
  liked,
  likeCount,
  onToggle,
  isPending = false,
  disabled = false,
  disabledReason,
  className = '',
}: LikeButtonProps) {
  const text = `${liked ? '已赞' : '赞'} ${likeCount}`
  // 无障碍名称 = 可见文案 + 原因。分开写会让「为什么点不了」只对鼠标用户可见，
  // 而用键盘/读屏的人恰好是最需要这个信息的人。
  const accessibleName = disabledReason ? `${text}，${disabledReason}` : text

  return (
    <button
      type="button"
      onClick={onToggle}
      // disabled 的按钮不触发 click，所以这里不需要再判一次 disabled
      disabled={disabled || isPending}
      aria-pressed={liked}
      aria-label={accessibleName}
      // 浏览器在 disabled 的按钮上仍然会显示 title 提示，鼠标用户能看到原因
      title={disabledReason}
      className={[
        'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors',
        liked
          ? 'border-rose-200 bg-rose-50 text-rose-600'
          : 'border-gray-300 text-gray-600 hover:bg-gray-50',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      ].join(' ')}
    >
      {/* 字形只是装饰，真正的状态由 aria-pressed 表达，别让读屏软件念出「♥」 */}
      <span aria-hidden="true" className="text-base leading-none">
        {liked ? '♥' : '♡'}
      </span>
      <span>{text}</span>
    </button>
  )
}
