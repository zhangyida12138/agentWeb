import { describe, expect, it } from 'vitest'

import {
  TAG_DESCRIPTION_MAX_LEN,
  TAG_NAME_MAX_LEN,
  TAG_NAME_RE,
  TAG_STATUS_LABEL,
  TAG_TYPE_LABEL,
  tagDescriptionError,
  tagNameError,
  toFormField,
} from './types'

/**
 * `types.ts` 里那几件纯函数的测试。
 *
 * 这里钉的主要是**契约**，而不是实现细节：
 *   · 长度上限必须与后端值对象里的数字一致（50 / 100）；
 *   · `TAG_NAME_RE` 必须与后端 `_TAG_RE` 逐字对齐——
 *     不一致的后果是「前端放行、后端拒绝」，一个只在边界输入下才出现的失败；
 *   · `toFormField` 必须同时认 `tag_names` 与 `name`。
 *
 * 最后一条是本文件存在的**主要**理由：后端同一个"名字有问题"会给出两个不同的 field
 * （格式错是 `40036 / tag_names`，撞名是 `40950 / name`）。只认其中一个的话，
 * 另一种错误会掉进"整表错误"分支——用户看到顶部一句话，输入框却毫无标记，
 * 而且这个 bug 在页面上很难稳定复现，只有把映射拿出来单独测才钉得住。
 */

describe('tagNameError', () => {
  it('空与全空白都算空', () => {
    expect(tagNameError('')).toBe('标签名不能为空')
    expect(tagNameError('   ')).toBe('标签名不能为空')
  })

  it('恰好等于上限放行，超出才报错', () => {
    // 边界必须两侧都测：写 `>=` 或 `>` 只差一个字符，而这一位正是
    // 「前端放行、后端拒绝」最容易出现的地方
    expect(tagNameError('a'.repeat(TAG_NAME_MAX_LEN))).toBeNull()
    expect(tagNameError('a'.repeat(TAG_NAME_MAX_LEN + 1))).toBe(
      `标签名最多 ${TAG_NAME_MAX_LEN} 位字符`,
    )
  })

  it('先量长度再查字符集，理由是两种失败的原因完全不同', () => {
    // 又超长又带 `#` 时应当报"太长"：用户一次只需要修一件事，
    // 报字符集的话他改完 `#` 还会再撞一次长度上限
    expect(tagNameError('#'.repeat(TAG_NAME_MAX_LEN + 1))).toBe(
      `标签名最多 ${TAG_NAME_MAX_LEN} 位字符`,
    )
  })

  it.each(['/', '\\', '#', '?', '%', 'a\tb', 'a\nb', 'a  b'])(
    '拒绝被 URL 或归化规则误伤的形状：%j',
    (name) => {
      // 前五个是 URL 的路径/片段/查询/编码起始符，标签会出现在
      // `GET /posts?tag=<slug>` 里，放行等于让链接在某一环被解析成别的东西。
      // 后面几个是空白：`"a  b"` 与 `"a b"` 归化出的 slug 相同，
      // 允许共存会让"按 slug 查"变得有歧义。
      // ⚠️ 这里**不含**首尾空格——那是 trim 掉的，见下面那个对照用例
      expect(tagNameError(name)).toBe('标签名不能包含 / \\ # ? %，也不能有连续空格')
    },
  )

  it.each(['机器学习', 'a b', 'a-b_c.d', '中文 混排 English'])('放行正常形状：%j', (name) => {
    expect(tagNameError(name)).toBeNull()
  })

  it('先 trim 再判断，所以首尾空格不算"非法字符"以外的额外错误', () => {
    // 这个用例是上一条的对照：`' 机器学习 '` 去空白后合法，
    // 于是它不该报"不能有连续空格"——判断必须发生在 trim 之后
    expect(tagNameError(' 机器学习 ')).toBeNull()
  })
})

describe('tagDescriptionError', () => {
  it('空描述不是错误：它表示"不要描述"，提交时转成 null', () => {
    // 如果这里报错，用户就**没法把描述清空**——把已有的描述删掉
    // 会变成一件做不到的事
    expect(tagDescriptionError('')).toBeNull()
    expect(tagDescriptionError('   ')).toBeNull()
  })

  it('只有超长才是错误，边界值放行', () => {
    expect(tagDescriptionError('a'.repeat(TAG_DESCRIPTION_MAX_LEN))).toBeNull()
    expect(tagDescriptionError('a'.repeat(TAG_DESCRIPTION_MAX_LEN + 1))).toBe(
      `标签描述最多 ${TAG_DESCRIPTION_MAX_LEN} 字`,
    )
  })
})

describe('toFormField', () => {
  it('两个后端 field 都映射到 name', () => {
    // 40036（TagName 值对象，blog 领域的遗留复数命名）
    expect(toFormField('tag_names')).toBe('name')
    // 40950（TagAlreadyExistsError，tag 领域自己的命名）
    expect(toFormField('name')).toBe('name')
  })

  it('description 原样映射', () => {
    expect(toFormField('description')).toBe('description')
  })

  it('不认识的字段与 undefined 都不映射，让调用方走"整表错误"', () => {
    // 宁可把一句说不出所以然的话显示在顶部，也不要挂到一个错误的输入框上——
    // 挂错地方比不挂更糟：用户会去改一个本来没问题的字段
    expect(toFormField('status')).toBeUndefined()
    expect(toFormField(undefined)).toBeUndefined()
    expect(toFormField('author_id')).toBeUndefined()
  })
})

describe('展示常量', () => {
  it('三个状态都有中文名，且互不相同', () => {
    // 写成映射表而不是三元表达式的意义就在这里：漏一个状态会在这条断言上挂掉，
    // 而不是在界面上静默显示成别的状态。「已下架」尤其不能被吃掉——
    // 它意味着标签不再进联想与公开列表，但历史文章上还挂着
    expect(Object.keys(TAG_STATUS_LABEL).sort()).toEqual(['abnormal', 'deleted', 'normal'])
    expect(new Set(Object.values(TAG_STATUS_LABEL)).size).toBe(3)
    expect(TAG_STATUS_LABEL.abnormal).toBe('已下架')
  })

  it('两种类型都有中文名', () => {
    expect(Object.keys(TAG_TYPE_LABEL).sort()).toEqual(['system', 'user'])
    // `system` 面向的是读者/作者，要传达"平台定的，你改不了"，所以是「官方」
    expect(TAG_TYPE_LABEL.system).toBe('官方')
  })

  it('TAG_NAME_RE 不接受空串', () => {
    // 空串由 tagNameError 单独报"不能为空"；正则本身不接受空，
    // 两处都必须挡住——正则放行空串的话，`tagNameError('')` 的
    // 第一条分支一旦被改坏就没有第二道防线了
    expect(TAG_NAME_RE.test('')).toBe(false)
  })
})
