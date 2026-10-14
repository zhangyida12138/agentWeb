import { Outlet } from 'react-router-dom'

import { SiteHeader } from './SiteHeader'

/**
 * 全站布局：页头 + 内容出口。
 *
 * **公开区与受保护区用的是同一个它**，这是「未登录也能看」这条决定的直接后果：
 *   两侧的视觉差异只应该来自「有没有人登录」，而不应该来自「在哪一套布局里」。
 *   拆成两个布局组件的话，页头的导航、登录/退出按钮迟早会长出两份略有差别的
 *   实现，而用户看到的差别是「同一个网站在两个页面上长得不一样」。
 *   真正需要区分的那件事（要不要先把人拦去登录页）由路由层的 RequireAuth 表达，
 *   它比布局更靠外、也更适合承担这个职责。
 *
 * 页头本体在 `SiteHeader`，它自己按登录态决定发出哪些查询：
 *   未登录时 `/auth/me` 与 `/auth/me/access` 都不发（两个都必然 401，
 *   而 401 会清掉本地登录态，于是「看别人的文章顺手把自己登出」）。
 *   这条规则放在页头里而不是这里，是因为只有页头知道「我需不需要用户名」。
 *
 * 页头是 `sticky` 的，所以这里**不需要**任何顶部留白——它仍占着文档流里的位置。
 * 这层包裹 div 也故意不加 `overflow`：给祖先加 `overflow: hidden/auto`
 * 会把 sticky 的参照系换掉，页头会当场不再固定。
 *
 * 主区用 `py-8` 而不是 `pt-8`：底部留白靠它，而顶部留白在滚动时
 * 是内容与页头之间的呼吸空间，两者需要同一个值才对称。
 */
export function SiteLayout() {
  return (
    <div className="min-h-screen">
      <SiteHeader />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
