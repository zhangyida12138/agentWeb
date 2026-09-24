import { useEffect, useState } from 'react'

/**
 * 返回 value 的防抖副本：delay 毫秒内的连续变更只保留最后一次。
 *
 * 典型用途是搜索框输入，避免每次按键都触发请求。
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return debouncedValue
}
