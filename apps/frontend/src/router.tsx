import { createBrowserRouter, Navigate } from 'react-router-dom'

import { RequireAuth } from './components/RequireAuth'
import { RequirePermission } from './components/RequirePermission'
import { UserManagementPage } from './features/access/UserManagementPage'
import { PERMISSION } from './features/access/permissions'
import { ChangePasswordPage } from './features/auth/ChangePasswordPage'
import { LoginPage } from './features/auth/LoginPage'
import { RegisterPage } from './features/auth/RegisterPage'
import { MyPostsPage } from './features/post/MyPostsPage'
import { PostDetailPage } from './features/post/PostDetailPage'
import { PostEditorPage } from './features/post/PostEditorPage'
import { PostListPage } from './features/post/PostListPage'
import { ProfilePage } from './features/profile/ProfilePage'
import { MyTagsPage } from './features/tag/MyTagsPage'
import { TagManagementPage } from './features/tag/TagManagementPage'
import { SiteLayout } from './layouts/SiteLayout'
import { HomePage } from './pages/HomePage'

/**
 * 路由表。
 *
 * 结构上分四层，顺序即语义：
 *   ① 无页头的公开页（/login、/register）
 *   ② 公开**阅读**区（/posts、/posts/:slug）——套 SiteLayout 但没有 RequireAuth
 *   ③ 守卫层（RequireAuth，只判登录态；RequirePermission，再判权限）
 *   ④ 布局层（SiteLayout，页头 + Outlet）
 *
 * ② 和 ③ 的区别就是「未登录也能看」这条决定的全部落点：
 *   登录/注册页不能套页头（否则会渲染出一个指向自己的「登录」链接），
 *   所以它们在布局**之外**；而文章列表与详情需要有页头、也需要能匿名访问，
 *   所以它们套布局但不套 RequireAuth。这两件事互不蕴含，
 *   拆成两个路由分支是最直接的表达方式。
 *
 * `/change-password` 放在守卫层**内部**：改密必须先登录（后端接口本身也要求
 * 当前用户，未登录访问只会拿到 401）。没有「忘记密码」那条公开路径，
 * 因为那需要邮件验证码一整套基础设施。
 *
 * 带权限的无形路由：把 RequirePermission 套在 path 上，而不是包住页面元素。
 *   守卫要先于页面挂载，才能在页面发请求之前就拦住。
 *   写成 `element: <RequirePermission><Page/></RequirePermission>` 也能跑，
 *   但那样页面元素会被立即创建（React 只是不用它），无权限的人依旧会触发
 *   页面的数据请求——正是我们想避免的。
 *
 * `/my/posts` 与接口路径 `/me/posts` 不同名，**不要顺手对齐**：
 *   一个是给用户看的 URL，一个是内部接口契约，没有必须一致的理由。
 *   真正必须避开的坑在后端（`/posts/mine` 会与 `/posts/{slug}` 撞模板），
 *   前端这条路不受影响。
 */
export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/register',
    element: <RegisterPage />,
  },

  // ② 公开阅读区：有页头，但不需要登录
  {
    element: <SiteLayout />,
    children: [
      { path: 'posts', element: <PostListPage /> },
      { path: 'posts/:slug', element: <PostDetailPage /> },
    ],
  },

  // ③④ 受保护区：先判登录，再进带页头的布局
  {
    element: <RequireAuth />,
    children: [
      {
        element: <SiteLayout />,
        children: [
          // index 路由不写 path：`/` 由父级的空 path 继承而来，
          // 同时写 index 和 path 会被 react-router 判为非法配置
          { index: true, element: <HomePage /> },
          { path: 'profile', element: <ProfilePage /> },
          { path: 'change-password', element: <ChangePasswordPage /> },

          // 「我的文章」只要求登录，不挂权限码：
          //   这些内容的所有者就是调用者本人，归属是比权限码更强的约束
          //   （权限码可被授予，归属不能）。这与「被收回作者角色的人
          //   仍然能翻到自己写过的草稿」是同一条理由。后端 `GET /me/posts` 亦然。
          { path: 'my/posts', element: <MyPostsPage /> },

          // 「我的标签」与「我的文章」同一条理由：只要求登录，不挂权限码。
          //   这一页的约束是**归属**（查询里带着 author_id = 我），不是权限——
          //   权限再收一遍也只是把"自己的东西"变成"自己有权看的自己的东西"。
          //   后端对应的实现是 `Tag.ensure_manageable_by` 里
          //   「user · 我的 → 任何人」那一行，两边必须是同一个口径。
          { path: 'my/tags', element: <MyTagsPage /> },

          // 编辑器两个入口的钥匙不同：新建看 post:create，改一篇已有的看 post:update。
          // 这里用「满足其一」是因为持有 `post:update_any` 的管理员
          // 即便没有 post:create 也应该能进编辑器改别人的文章——
          // 与页头里 `canCreatePost` 的口径必须一致，否则会出现
          // 「导航里有入口、点进去却说没权限」。
          {
            element: (
              <RequirePermission
                permission={[PERMISSION.POST_CREATE, PERMISSION.POST_UPDATE_ANY]}
              />
            ),
            children: [
              { path: 'editor', element: <PostEditorPage /> },
              { path: 'editor/:slug', element: <PostEditorPage /> },
            ],
          },

          {
            element: <RequirePermission permission={PERMISSION.USER_LIST} />,
            children: [{ path: 'admin/users', element: <UserManagementPage /> }],
          },

          // 标签管理挂 `tag:manage`，与后端的路由守卫**逐个接口对齐**：
          //   POST /tags、PATCH /tags/{id}/status、DELETE /tags/{id} 三条都挂着它。
          //   也就是说「能到达这一页」和「能做这里的每个动作」是同一个条件，
          //   不会出现"进来了但按钮点不动"的中间态。
          //   页面里 `useTagsQuery(..., { enabled: managesTags })` 用的是同一个
          //   判断——守卫、请求、按钮显隐三者必须同源，否则空窗期一定有人看见错的东西。
          {
            element: <RequirePermission permission={PERMISSION.TAG_MANAGE} />,
            children: [{ path: 'admin/tags', element: <TagManagementPage /> }],
          },
        ],
      },
    ],
  },
  {
    // 兜底：未知路径统一回首页。
    // 首页在受保护区里，所以游客输错地址会先被守卫拦到登录页——
    // 这是期望行为（他的意图本来就不明确，给一个确定的落点比停在白屏好）。
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
