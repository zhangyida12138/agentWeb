import { describe, expect, it } from 'vitest'

import { canChangeTagStatus, canDeleteTag, canEditTag, canSeeAllTagStatuses } from './permissions'

import type { Tag } from './types'

/**
 * 标签的可见性/可操作性判定（纯函数）。
 *
 * 这个文件是整套标签前端里性价比最高的一处测试：**没有任何渲染、没有请求、没有时序**，
 * 但 `canEditTag` 的四条判断是全模块最容易写错的地方——它同时依赖
 * "谁在看"（权限码 + 用户 id）和"看的是哪个"（状态 + 类型 + 归属），
 * 两个维度交叉出十来种组合，而其中大部分在手工点界面时**碰不到**：
 *
 *   · 「系统标签 + 普通作者」要在管理员建过官方标签之后才可能点到；
 *   · 「无主标签」需要创建者账号被删掉才会出现；
 *   · 「已删除 + 管理员」在删除之后那一行就从「已删除」tab 里消失了，
 *     想验证只能手工把 URL 的 status 改回去。
 *
 * 也就是说这些组合**只能靠这里兜住**。渲染层的测试（MyTagsPage / TagManagementPage）
 * 只抽查界面上真的会出现按钮的那几条路径。
 */

const TAG_MANAGE = 'tag:manage'
const AUTHOR_ID = '018f0000-0000-7000-8000-000000000001'
const OTHER_ID = '018f0000-0000-7000-8000-000000000002'

function tag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: '018f0000-0000-7000-8000-0000000000aa',
    name: 'python',
    slug: 'python',
    description: null,
    status: 'normal',
    type: 'user',
    author_id: AUTHOR_ID,
    post_count: 0,
    ...overrides,
  }
}

/** 管理员：只有 tag:manage 这一个码与标签有关，其余码不该影响结论。 */
const ADMIN = [TAG_MANAGE, 'user:list']
/** 作者：能写文章（有 post:create），但没有任何 tag:* 权限。 */
const AUTHOR = ['post:create', 'post:update']
const GUEST: readonly string[] | undefined = undefined

describe('canEditTag —— 改名 / 改描述', () => {
  it('作者能改自己创建的普通标签', () => {
    expect(canEditTag(AUTHOR, tag(), AUTHOR_ID)).toBe(true)
  })

  it('作者改不了别人的标签', () => {
    // 后端对这条回 40350。前端必须同意——否则界面上会有一个永远失败的按钮
    expect(canEditTag(AUTHOR, tag({ author_id: OTHER_ID }), AUTHOR_ID)).toBe(false)
  })

  it('无主标签（author_id 为 null）对作者不可编辑', () => {
    // 这里刻意不断言"等价于别人的标签"：无主是**第三种**状态。
    // 把它误判成"有个主人只是不是我"会让人去找管理员要授权，
    // 而真正的答案是「谁都认领不了，只有管理员能处置」
    expect(canEditTag(AUTHOR, tag({ author_id: null }), AUTHOR_ID)).toBe(false)
  })

  it('管理员能改别人的普通标签', () => {
    expect(canEditTag(ADMIN, tag({ author_id: OTHER_ID }), AUTHOR_ID)).toBe(true)
  })

  it('管理员也能改无主标签（否则它们永远没人能收拾）', () => {
    expect(canEditTag(ADMIN, tag({ author_id: null }), AUTHOR_ID)).toBe(true)
  })

  it('系统标签：只有管理员能改，作者一律不能', () => {
    expect(canEditTag(ADMIN, tag({ type: 'system', author_id: OTHER_ID }), AUTHOR_ID)).toBe(true)
    expect(canEditTag(AUTHOR, tag({ type: 'system', author_id: OTHER_ID }), AUTHOR_ID)).toBe(false)
  })

  it('系统标签即使 author_id 恰好是自己，作者也不能改', () => {
    // 顺序问题：②（system 先判）必须早于 ④（归属）。
    // 把两条调换，这条会变成 true——而界面上会多出一个永远 40051 的按钮
    expect(canEditTag(AUTHOR, tag({ type: 'system', author_id: AUTHOR_ID }), AUTHOR_ID)).toBe(false)
  })

  it('已删除的标签，连管理员都不能改', () => {
    // 后端 `ensure_not_deleted()` 对已删除的标签回 **404**，
    // 不是"没权限"。既然那个资源在语义上不存在了，就不该再给编辑入口
    expect(canEditTag(ADMIN, tag({ status: 'deleted' }), AUTHOR_ID)).toBe(false)
  })

  it('已下架的标签仍然可以改（下架是"藏起来"，不是"没了"）', () => {
    // 这正是作者会做的事：标签被下架后回来补描述，好让管理员同意恢复
    expect(canEditTag(AUTHOR, tag({ status: 'abnormal' }), AUTHOR_ID)).toBe(true)
  })

  it('未登录（拿不到用户 id / 权限码）时，什么都改不了', () => {
    // 第 ③④ 两条判断都依赖"知道我是谁"。`currentUserId` 为 undefined 时
    // `isTagAuthor` 会返回 false——这就是游客拿到 false 的**唯一**原因，
    // 所以这条断言其实在测那个 `!currentUserId` 的提前返回
    expect(canEditTag(GUEST, tag(), undefined)).toBe(false)
    expect(canEditTag([], tag(), undefined)).toBe(false)
    // 有权限码但没有 user 的畸形状态：仍然不该放行到"作者"这一支
    expect(canEditTag([], tag(), undefined)).toBe(false)
  })
})

describe('canChangeTagStatus —— 下架 / 恢复', () => {
  it('只认 tag:manage，作者即便拥有这个标签也不行', () => {
    // 归属换不来这个动作：撤掉一个标签会同时影响**别人**已发布的文章
    expect(canChangeTagStatus(ADMIN)).toBe(true)
    expect(canChangeTagStatus(AUTHOR)).toBe(false)
    expect(canChangeTagStatus(GUEST)).toBe(false)
  })
})

describe('canDeleteTag —— 软删除', () => {
  it('管理员能删除未删除的标签', () => {
    expect(canDeleteTag(ADMIN, tag())).toBe(true)
  })

  it('已删除的行不再显示「删除」（DELETE 幂等，但按钮会误导）', () => {
    // 那一行正确的操作是「恢复」。留一个"删除"按钮会让管理员
    // 以为上一次没生效，然后对着它反复点
    expect(canDeleteTag(ADMIN, tag({ status: 'deleted' }))).toBe(false)
  })

  it('作者不能删除任何标签，包括自己建的', () => {
    expect(canDeleteTag(AUTHOR, tag())).toBe(false)
  })
})

describe('canSeeAllTagStatuses —— 能否看到非 normal 的档位', () => {
  it('与 tag:manage 同源', () => {
    expect(canSeeAllTagStatuses(ADMIN)).toBe(true)
    expect(canSeeAllTagStatuses(AUTHOR)).toBe(false)
    expect(canSeeAllTagStatuses(GUEST)).toBe(false)
  })
})
