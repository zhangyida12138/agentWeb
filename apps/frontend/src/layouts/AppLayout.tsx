import { Outlet } from 'react-router-dom'

import { SiteHeader } from './SiteHeader'

/**
 * 受保护区域的布局：页头 + 内容出口。
 *
 * 页头本体在 `SiteHeader`，与公开区域共用——两边长得一样是有意的，
 * 差异只该来自「有没有人登录」，不该来自「在哪一套布局里」。
 *
 * 这个组件现在只剩两件事：页头，和内容容器。它不再自己查 `/auth/me`：
 *   那是页头的职责（页头要显示用户名），而公开区域也需要同一份数据。
 *   留在这里的话，公开区域要么拿不到，要么得再查一遍。
 *
 * 「token 失效了就自动回登录页」这件事仍然成立，只是责任换了位置：
 *   `SiteHeader` 的 `/auth/me` 撞到 401 → api 层清登录态 →
 *   `RequireAuth` 订阅到变化 → 重定向到登录页。
 *   所以这里不需要任何定时器或显式的校验逻辑。
 */
export function AppLayout() {
  return (
    <div className="min-h-screen">
      <SiteHeader />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
