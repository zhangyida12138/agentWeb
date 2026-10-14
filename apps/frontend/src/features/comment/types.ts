/**
 * 评论相关的类型。字段名与后端 `app/presentation/api/v1/schemas/comment.py` 逐字对应。
 *
 * 结构上只有一件事需要注意：`CommentNode.replies` 是**自引用**的。
 *   后端也是自引用（响应里带嵌套的回复），而且**深度不设限**——
 *   回复的回复原样挂在被回复的那条下面，后端不做任何折算。
 *   类型写成自引用正好对上这个形状，前端不必维护两套类型（「跟帖」和「回复」）
 *   再互相转换。
 *
 * ⚠️ 「显示时缩进几层」是**界面**的事，不归这里管：
 *    实际渲染只有两个缩进级（根评论，以及所有回复共用的那一层，见 `CommentItem`），
 *    第三层、第四层……都停在第一层回复的位置上。
 *    所以**不要**用 `replies` 的嵌套深度去算 padding，那会把长对话挤出屏幕。
 */

/**
 * 评论正文长度上限。
 *
 * 与后端 `domain/interaction/value_objects.py::COMMENT_CONTENT_MAX_LEN` 保持一致，
 * 同时后端 Pydantic 的 `CreateCommentRequest.content` 也用它做 `max_length`。
 * 三处同一个数字看起来啰嗦，但这是**有意留出的三处**：
 *   前端这一处是为了在输入框上写 `maxLength`（让用户根本打不出超长内容），
 *   schema 那一处是为了让超长请求得到 40000 而不是 40040（它是「请求形状不对」），
 *   领域那一处才是真正的业务不变式（任何入口进来都得守住）。
 * 只有领域那处是权威；前两处是「提前拦一下、让错误更好懂」。
 */
export const COMMENT_CONTENT_MAX_LEN = 2000

/** 一条评论（含它下面的回复）。对应 `CommentResponse`。 */
export interface CommentNode {
  id: string
  post_id: string
  /** 作者的用户 id。用来做 key、做「这条是不是我发的」的判断，不直接显示。 */
  author_id: string
  /**
   * 评论者的显示名，由**后端**解析好（`display_name` 优先，回落 `username`）。
   *
   * 它是展示字段，不是另一个实体的引用，所以直接渲染就行。
   * 前端绝不要拿着 `author_id` 去一个个拉 `/users/{id}`——
   * 那是把 N+1 从数据库搬到了浏览器，而且在匿名可读的评论区里，
   * 那些请求会因为需要鉴权而 401/403。
   */
  author_display_name: string
  /** 被回复的评论 id；根评论为 null。 */
  parent_id: string | null
  /**
   * 被回复者的显示名；根评论为 null。
   *
   * 与 `parent_id` 同生共死（要么都有、要么都是 null），
   * 所以界面只看这对字段就能决定要不要渲染「回复 xxx」，不用判两次。
   */
  parent_author_display_name: string | null
  /**
   * 评论正文。**被撤回时是空串**，同时 `is_deleted` 为 true。
   *
   * 后端不会把撤回的内容传出来（撤回的语义就是「读不到了」），
   * 所以前端拿到的空串不是「还没加载」，就是「已经撤回」——
   * 判断只能看 `is_deleted`，不要写 `!content`。
   */
  content: string
  /** 是否已被撤回。为 true 时渲染墓碑占位块，而不是把它从列表里抹掉。 */
  is_deleted: boolean
  like_count: number
  liked_by_me: boolean
  created_at: string
  updated_at: string
  /** 这条评论下面的回复，含更深层的回复——深度由真实对话决定，不设上限。 */
  replies: CommentNode[]
}

/**
 * 评论分页。对应 `CommentPageResponse`。
 *
 * ⚠️ `total` 是**根评论数**，不是评论总数。
 *    分页的单位是「一段对话」（一条根评论 + 它的全部回复），
 *    因为把回复也当成独立分页项会出现「一条对话被拆到两页上」。
 *    所以这里不能用 `total` 去算「一共有多少条评论」——
 *    那个数字来自 `PostInteractionStats.comment_count`。
 */
export interface CommentPage {
  items: CommentNode[]
  /** 根评论总数（「段对话」的数量），分页用。 */
  total: number
  offset: number
  limit: number
}

/** 发表评论 / 回复入参（`CreateCommentRequest`）。 */
export interface CreateCommentInput {
  content: string
  /** 要回复的评论 id。不传 = 发表根评论。 */
  parent_id?: string
}

/** 评论列表查询参数。 */
export interface CommentListParams {
  offset?: number
  limit?: number
}
