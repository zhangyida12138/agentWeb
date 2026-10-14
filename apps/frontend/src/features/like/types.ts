/**
 * 点赞（like）相关的类型。
 *
 * 字段名与后端 `app/presentation/api/v1/schemas/like.py` **逐字对应**（snake_case），
 * 理由与 `features/post/types.ts` 相同：多写一层「转驼峰」的规则，
 * 就要多维护一份「嵌套 / 数组 / null 怎么转」的定义，而收益只是少几个下划线。
 */

/**
 * 可以被点赞的目标类型。
 *
 * 写成常量对象 + 派生联合类型，而不是裸的 `'post' | 'comment'`：
 *   调用处要用 `LIKE_TARGET_TYPE.POST` 这种有名字的写法（写错立刻是编译错误），
 *   而后端 `domain/interaction/value_objects.py::LikeTargetType` 里也是同样的两个字面量。
 *
 * ⚠️ 这两个值会被**原样发到后端**并参与唯一约束（`uq_likes_user_target`）。
 *    改这里的字符串等于改数据分区：写错的表现是「赞数永远为 0」，
 *    而不是报错（后端会把未知类型的点赞写进一个没人读的分区）。
 */
export const LIKE_TARGET_TYPE = {
  POST: 'post',
  COMMENT: 'comment',
} as const

export type LikeTargetType = (typeof LIKE_TARGET_TYPE)[keyof typeof LIKE_TARGET_TYPE]

/** 点赞 / 取消点赞入参（`ToggleLikeRequest`）。 */
export interface ToggleLikeInput {
  target_type: LikeTargetType
  /** 目标 id，**不是** slug——文章改永久链接不该让赞数搬走。 */
  target_id: string
}

/** 点赞操作后的状态（`LikeResultResponse`）。 */
export interface LikeState {
  target_type: string
  target_id: string
  /** 操作**之后**是否处于已点赞状态（不是「刚才这一下是赞还是取消」）。 */
  liked: boolean
  /** 操作之后的真实赞数：后端实时聚合得出，不是前端 ±1 猜的。 */
  like_count: number
}

/**
 * 一篇文章的互动统计（`PostInteractionStatsResponse`）。
 *
 * 这里的两个数字口径不同，页面上的文案必须区分开：
 *   `like_count` 是**文章本身**的赞数，不含评论的赞（评论的赞各算各的）；
 *   `comment_count` 是未撤回的评论**总数**（根评论 + 回复），
 *   和评论列表接口返回的 `total`（**根评论数**，即「一段对话」的数量）不是一个数。
 * 两个接口各按各的单位说话，前端若混用会出现「标题写着 5 条评论、列表里只有 2 条」。
 */
export interface PostInteractionStats {
  post_id: string
  like_count: number
  comment_count: number
  /** 当前访问者是否赞过这篇文章。**游客恒为 false**，不是缺字段。 */
  liked_by_me: boolean
}
