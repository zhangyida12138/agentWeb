import { NavLink } from 'react-router-dom'

import { useMyAccessQuery } from '../features/access/hooks'
import { PERMISSION, hasPermission } from '../features/access/permissions'
import { useMeQuery } from '../features/auth/hooks'
import { canCreatePost } from '../features/post/permissions'
import { clearAuth, useAuth } from '../stores/auth'

/**
 * 全站页头。
 *
 * 公开区域与受保护区共用同一个页头，**不是**为了少写代码，而是因为
 * 「未登录也能看」这个决定要求两侧的差异只在于「有没有人登录」，
 * 而不是「在哪一套布局里」。拆成两个页头组件的话，导航项、登录/退出按钮
 * 这些地方迟早会长出两份略有差别的实现，而用户看到的差别是
 * 「同一个网站在两个页面上长得不一样」。
 *
 * 组件的全部差异都收在 `navItems` 这一个函数里：它按登录态和权限快照
 * 决定露出哪些入口。权限不够的入口**不渲染**（而不是渲染成置灰）——
 * 置灰的入口对普通用户是纯粹的干扰，他既永远点不亮，也不知道为什么。
 * 「看不见入口」+「直接敲地址时明说缺哪个权限」（RequirePermission），
 * 这组组合才是能自解释的。
 *
 * 页头用 `sticky top-0` 固定在顶部，而不是 `fixed`：
 *   `fixed` 会把元素抽离文档流，于是必须再给主区补一段等高 padding，
 *   而那个数字一旦和页头实际高度对不上（换行、字号、加了公告条），
 *   就会出现「内容顶部被压住」或「页头和内容之间多一道空白」。
 *   `sticky` 仍占着原来的位置，只是滚动时黏在视口边缘——零额外补偿。
 *   前提是祖先链上没有 `overflow: hidden/auto`（有的话黏不住），
 *   布局那边是普通的 div，满足条件；将来若给外层加内滚动要一并检查这里。
 *
 * `z-20` 压在内容之上、压在弹窗（`z-50`）之下：回到页面顶部的用户
 * 不该看到标题从页头底下穿过去，而弹窗必须盖住一切。
 * 背景保持不透明（`bg-white`），否则内容会从半透明页头里透出来。
 */

interface NavItem {
  to: string
  label: string
  /** 精确匹配（首页要它：否则 `/` 会匹配到所有路径） */
  end: boolean
}

function buildNavItems(authenticated: boolean, codes: readonly string[] | undefined): NavItem[] {
  // 游客只有文章列表：**这一条是「未登录也能看」的落点**。
  // 其余入口（首页/个人中心/我的文章）都是登录后才存在的页面，
  // 未登录时渲染出来只会点一下就跳登录页。
  if (!authenticated) {
    return [{ to: '/posts', label: '文章', end: false }]
  }

  const items: NavItem[] = [
    { to: '/', label: '首页', end: true },
    { to: '/posts', label: '文章', end: false },
    { to: '/my/posts', label: '我的文章', end: false },
    // 标签的入口分两层，与后端的两个维度一一对应：
    //   「我的标签」只要求登录（和「我的文章」一样，依据是归属不是权限），
    //   「标签管理」要 tag:manage。普通用户看不到第二个入口——
    //   置灰的入口对他永远是灰的，他不知道该找谁点亮，也不知道点亮了能干什么。
    { to: '/my/tags', label: '我的标签', end: false },
  ]

  // 写文章要看的是「能不能产出文章」。`post:update_any` 也算：
  // 持有它的人可以编辑别人的文章，那他当然也能写自己的
  // （判定收口在 features/post/permissions.ts 的 canCreatePost）。
  if (canCreatePost(codes)) {
    items.push({ to: '/editor', label: '写文章', end: false })
  }

  items.push({ to: '/profile', label: '个人中心', end: false })

  if (hasPermission(codes, PERMISSION.USER_LIST)) {
    items.push({ to: '/admin/users', label: '用户管理', end: false })
  }

  // 标签管理的入口**只**挂 tag:manage，不是"能看标签就给"：
  //   这一页的默认筛选是"全部 + 全站"，「我的标签」那一页已经覆盖了
  //   "我想整理自己的东西"这个需求。给普通作者一个会 403 的入口，
  //   只会让他怀疑自己权限配错了。
  if (hasPermission(codes, PERMISSION.TAG_MANAGE)) {
    items.push({ to: '/admin/tags', label: '标签管理', end: false })
  }

  return items
}

export function SiteHeader() {
  const auth = useAuth()
  const authenticated = Boolean(auth.token)

  /**
   * 两个查询都按登录态开合，**这是公开区域能正常工作的关键**。
   *
   * `/auth/me` 与 `/auth/me/access` 都要求认证，未登录时必然 401。
   * 而 api 层在 401（除密码错误外）时会清掉本地登录态——
   * 也就是说，一次注定失败的请求会去动用户的登录状态。
   * 游客打开一篇文章，页头顺手发两个 401 请求，结果就是
   * 「看别人的文章结果被登出了」。用 enabled 从源头掐掉这两个请求。
   */
  useMeQuery({ enabled: authenticated })
  const accessQuery = useMyAccessQuery({ enabled: authenticated })

  const navItems = buildNavItems(authenticated, accessQuery.data?.permission_codes)
  const user = auth.user
  const displayName = user?.display_name || user?.username || '未登录'

  return (
    <header className="sticky top-0 z-20 border-b border-gray-200 bg-white">
      <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
        <div className="flex items-center gap-6">
          <NavLink to={authenticated ? '/' : '/posts'} className="font-bold text-gray-900">
            AgentWeb
          </NavLink>
          <nav className="flex items-center gap-4">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `text-sm transition-colors ${
                    isActive ? 'font-medium text-brand' : 'text-gray-600 hover:text-gray-900'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {authenticated ? (
            <>
              {user?.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt=""
                  className="h-7 w-7 rounded-full bg-gray-100 object-cover"
                />
              ) : (
                // 没有头像时用显示名首字符兜底，避免一个灰色问号方块
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand text-xs text-white">
                  {displayName.slice(0, 1).toUpperCase()}
                </span>
              )}
              <span className="max-w-[10rem] truncate text-sm text-gray-700">{displayName}</span>
              <button
                type="button"
                // 退出**只清登录态、不做跳转**，两个区域各自得到正确的行为：
                //   受保护区：RequireAuth 订阅了登录态，无 token 时它自己会重定向到登录页，
                //             不需要这里再推一下；
                //   公开区：正读着一篇文章的游客点「退出」，应当留在原地继续读，
                //          而不是被踢到登录页——退出登录不等于离开内容。
                onClick={() => clearAuth()}
                className="text-sm text-gray-500 transition-colors hover:text-red-600"
              >
                退出
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="text-sm text-gray-600 hover:text-gray-900">
                登录
              </NavLink>
              <NavLink
                to="/register"
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                注册
              </NavLink>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
