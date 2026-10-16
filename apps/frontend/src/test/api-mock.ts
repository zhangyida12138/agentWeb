import { vi } from 'vitest'

/**
 * fetch 打桩工具。
 *
 * 为什么要按「信封」来造响应：后端所有非流式响应都是 `{code,data,message}`，
 * 测试里如果直接返回裸数据，前端 api 层会因为「响应格式不符合预期」而抛错，
 * 测出来的就不是真实行为。所以这里强制走信封。
 *
 * 不用 MSW：本项目当前只有 5 个接口，为它引入一个拦截层（还要配 handler 文件、
 * 处理 service worker）不划算。等接口多了、需要复用同一份 handler 做开发态 mock 时再换。
 */

export interface MockReply {
  status?: number
  code?: number
  message?: string
  data?: unknown
}

export type FetchHandler = (url: string, init: RequestInit) => MockReply

/**
 * 无内容的状态码。
 *
 * `new Response(body, { status: 204 })` 会**抛 TypeError**
 * （"Response with null body status cannot have body"），不是返回一个空响应。
 * 而删除类接口（文章、评论、标签）后端回的都是 204——
 * 不单独处理的话，这类用例里 fetch 会以一个 TypeError 结堆，
 * 前端 catch 到之后弹一个"删除失败，请稍后重试"，
 * 于是测试看到的是"弹窗关不掉"这样一个与真实原因毫无关系的现象。
 */
const NULL_BODY_STATUSES = new Set([204, 205, 304])

/** 替换全局 fetch，返回的 mock 可用于断言「请求了几次、带了什么 body」。 */
export function installFetchMock(handler: FetchHandler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input)
    const { status = 200, code = 0, message = 'ok', data = null } = handler(url, init ?? {})

    if (NULL_BODY_STATUSES.has(status)) return new Response(null, { status })

    return new Response(JSON.stringify({ code, message, data }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })

  vi.stubGlobal('fetch', mock)
  return mock
}

/** 解析某次调用的 JSON 请求体，断言 PATCH 只带了预期字段时用。 */
export function bodyOf(init: RequestInit | undefined): unknown {
  if (!init?.body || typeof init.body !== 'string') return null
  return JSON.parse(init.body)
}
