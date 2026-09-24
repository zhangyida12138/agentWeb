/** 把后端返回的 ISO 时间字符串格式化为 `YYYY-MM-DD HH:mm`（本地时区）。 */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  fallback = '-',
): string {
  if (value === null || value === undefined || value === '') {
    return fallback
  }

  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) {
    return fallback
  }

  const pad = (input: number) => String(input).padStart(2, '0')

  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
