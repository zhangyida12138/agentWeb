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

/** 替换全局 fetch，返回的 mock 可用于断言「请求了几次、带了什么 body」。 */
export function installFetchMock(handler: FetchHandler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input)
    const { status = 200, code = 0, message = 'ok', data = null } = handler(url, init ?? {})
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
