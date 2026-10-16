# 下一步开发任务：M4 博客文章（后端 P4 + 前端 P8.1 / P8.2）

> 生成日期：2026-10-14
> 依据：[PLAN.md](./PLAN.md) 的里程碑顺序 + 仓库当前真实进度核对。
> 配套阅读：[ARCHITECTURE.md](./ARCHITECTURE.md)（分层怎么落）、[backend.md](./backend.md)（范式手册）。
>
> **状态（2026-10-14 更新）：M4 与 M5 都已执行完毕。** M4 的落地差异见 §6，
> M5 的落地差异见 **§6.5**（其中有两处**推翻**了原 PLAN 5.x 的措辞：评论树是任意深度、
> 作者名由后端批量解析）。本文件保留原始方案的写法不改，只追加执行结果。

---

## 0. 结论先行：下一步就是「博客文章」，两端一起做

核对仓库现状后的进度表：

| 里程碑 | 阶段 | 状态 | 证据 |
| --- | --- | --- | --- |
| M0 | P0 环境基座 | ✅ 完成 | `docker-compose.yml` / 根 `Makefile` 可用 |
| M1 | P1 后端内核 | ✅ 完成 | `core/` 六个模块 + `middleware/` 四件套齐备 |
| M2 | P2 身份认证 | ✅ 完成 | `domain/identity/` + `application/identity/` + `endpoints/auth.py` |
| M3 | P3 权限 RBAC | ✅ 完成 | `domain/access/` + `application/access/` + `endpoints/{users,roles}.py` + `core/seed.py` |
| M4 | P4 博客文章 | ✅ 完成 | `domain/blog/` + `application/blog/` + `endpoints/posts.py` + 迁移 `73556e70e308`（见 §6） |
| M5 | P5 评论点赞 | ✅ 完成 | `domain|application/interaction/` + `endpoints/{comments,likes}.py` + 迁移 `db936358c4a8`（见 §6.5） |
| M6 | P6 AI Agent | ⬜ 未开始 | 前置 M2（可并行） |
| M7 | P7 前端基座 | ✅ 完成 | `lib/api.ts`、`lib/query-client.ts`、`stores/auth.ts` |
| M8 | P8 前端业务页 | ✅ 完成 | 8.1/8.2 见 §6；8.5 个人中心、8.6 管理后台；8.3 评论/点赞见 §6.5 |

**为什么是它，而不是别的**：

- `identity`（M2）与 `access`（M3）已经让「谁能做什么」跑通了，但没有**做的东西**——`post:*` 四个权限码已经在种子数据里空转，`ROLE_SPECS` 里 `author` 的「可创作与管理自己的文章」目前没有任何接口来兑现。
- M5（评论点赞）和 M8 的其余部分都硬依赖 M4（没有文章，评论无宿主）。
- M6（Agent）虽然技术上只依赖 M2，但它是唯一需要外部 LLM key 的模块，先做会让「本机能否跑起来」变成运气问题。

**本步交付的验收主线**（来自 PLAN 4.6）：`非作者 403`、`列表分页`、`软删不出现`。

---

## 1. 本步范围

### 后端（P4）

| 层 | 新增 |
| --- | --- |
| `domain/blog/` | `entities.py`、`value_objects.py`、`repositories.py`、`exceptions.py` |
| `domain/access/` | 修改：`entities.py` 追加 2 个权限码 + 更新角色矩阵 |
| `application/blog/` | `dto.py`、`use_cases.py` |
| `infrastructure/persistence/` | `models/{post,tag,post_tag}.py`、`mappers/post.py`、`repositories/post.py`，并改 `models/__init__.py` |
| `presentation/` | `api/v1/schemas/post.py`、`api/v1/endpoints/posts.py`，改 `router.py`、`dependencies.py` |
| `migrations/versions/` | 一个新的 blog 迁移 |
| `tests/` | `unit/test_post.py`、`integration/test_posts_api.py` |

### 前端（P8.1 / P8.2）

| 位置 | 新增 |
| --- | --- |
| `src/features/post/` | `types.ts`、`api.ts`、`hooks.ts`、`PostListPage.tsx`、`PostDetailPage.tsx`、`MyPostsPage.tsx`、`editor/PostEditorPage.tsx` |
| `src/features/access/permissions.ts` | 修改：补 `post:*` 权限码常量 |
| `src/router.tsx` | 修改：加 4 条路由 |
| `src/layouts/AppLayout.tsx` | 修改：导航加「文章」「我的文章」「写文章」 |
| `package.json` | 新增 Markdown 渲染依赖 |

### 明确不做（留给后续里程碑）

- 评论、点赞（M5）
- 标签**管理**后台（本期标签只支持「随文章提交、自动创建」，不做独立 CRUD）

> ⚠️ **本条已被推翻（后续补做）**：标签后来长出了独立上下文。
> 后端见 `domain|application|infrastructure|presentation` 下的 `tag/`，
> 迁移 `8c41d2f7a930_add_tag_management_fields.py`，
> 接口 `GET|POST /api/v1/tags`、`PUT|DELETE /api/v1/tags/{id}`、`PATCH /api/v1/tags/{id}/status`，
> 新权限码 `tag:manage`（仅 admin）。要点集中在 `ARCHITECTURE.md` §7.6。

- 文章全文搜索、富文本编辑器（本期用 Markdown 纯文本域）
- 图片上传（`cover_url` 本期只存外链字符串）

---

## 2. 开工前必须拍板的 4 个决策

这四条不定下来，代码写到一半会返工。

### 2.1 「只有作者能改自己的文章」怎么落地 ⭐ 最关键

**问题**：`post:update` 这个权限码 `author` 和 `admin` **都有**（见 `domain/access/entities.py` 的 `_AUTHOR_PERMISSIONS` 与 `_ALL_PERMISSION_CODES`）。RBAC 是布尔判断，表达不了「只有你自己」。

**若直接照搬现状**，会出现两种错误之一：

- 只判 `post:update` → **任何 author 都能改别人的文章**（严重越权）；
- 再判 `post.author_id == current_user.id` → **admin 改不了别人的文章**（丢了管理能力）。

**推荐方案**：把「行级归属」和「管理特权」拆成两件事。

```
编辑/发布/删除的判定顺序：
    ① 有 post:update（author 或 admin）        → 通过 RBAC 守卫
    ② 是作者本人                                → 放行
    ③ 否则：有 post:update_any 吗？             → 有则放行（admin）
                                             → 没有则 403
```

需要在 `domain/access/entities.py` 追加两个权限码：

| 权限码 | 名称 | 授予 |
| --- | --- | --- |
| `post:update_any` | 编辑任意文章 | **仅 admin** |
| `post:delete_any` | 删除任意文章 | **仅 admin** |

`author` 仍只持有 `post:update` / `post:delete`（表示「可编辑/删除」这一大类能力），归属校验由领域方法承担。

> 加权限码是**安全**的：`core/seed.py` → `SqlAccessRepository.sync_catalog()` 的 `_sync_permissions` 会补建缺失行、`_sync_role_permissions` 会补建绑定（不做删除），重启即生效。

### 2.2 「不存在」和「不是你的」分别返回什么

| 场景 | 返回 | 理由 |
| --- | --- | --- |
| 文章不存在 / 已软删 | **404** `40430` | — |
| 文章存在，但不是你的，且无 `post:update_any` | **403** `40330` | 文章本身是公开的，隐藏它没有意义，直接说「没权限」比 404 更好排查 |

注意：**不要**为了「防信息泄露」把 403 也伪装成 404——文章内容是公开可读的，伪装没有收益，只会让前端无法区分「文章没了」和「你越权了」。

### 2.3 状态机的准确形状

PLAN 里同时出现了「草稿与已发布状态机」和 4.1 的 `draft→published→archived`，但 API 只给了 `publish` / `unpublish`。本期按下面这张表实现（`archived` 就是「下架」）：

| 当前 | 动作 | 结果 | 副作用 |
| --- | --- | --- | --- |
| `draft` | `publish` | `published` | 写 `published_at`（**仅首次**，重新发布不覆盖原首发时间） |
| `published` | `unpublish` | `archived` | `published_at` 保留 |
| `archived` | `publish` | `published` | 不动 `published_at` |
| 任意 | `update` | 状态不变 | 编辑**已发布**文章不自动回草稿（避免「改个错别字就消失」） |
| 任意（未软删） | `delete` | 置 `deleted_at` | 软删，行仍在 |

非法转移（如 `draft → unpublish`）抛领域异常 `40030`，不做静默容忍。

### 2.4 前端文章页是否要登录才能看

- 后端 `GET /posts`、`GET /posts/{slug}` **无需鉴权**（PLAN 第五节）。
- 但当前 `router.tsx` 把所有非 `/login`、`/register` 的路由都套在 `RequireAuth` 里。

**本期建议**：**保持 RequireAuth**。理由是把「公开可访问」做对需要把 `AppLayout` 拆成「公开布局 + 登录后布局」两套（未登录时页头不能显示头像/退出/写文章），这是 M8 之外的一次布局重构，混在 M4 里会让本步不可验收。先让登录用户可用，**留一个 TODO**，等 M8 收尾时再拆。

> 若你希望本期就做公开访问，请回复一声，我会把 `AppLayout` 拆成 `PublicLayout` + `AuthedLayout` 并调整导航。

---

## 3. 后端任务清单

### 3.1 `domain/blog/`（先写，且必须先写）

- [ ] **`exceptions.py`** —— 错误码避开已占用的 `40010~40911`（identity）与 `40320/40420/40920`（access），从 `40030` 起编：

| 异常 | code | HTTP | 抛出点 |
| --- | --- | --- | --- |
| `InvalidTitleError` | 40030 | 400 | 标题为空或超长 |
| `InvalidPostStatusTransitionError` | 40031 | 400 | 非法状态转移 |
| `InvalidSlugError` | 40032 | 400 | 手填 slug 不合规 |
| `PostForbiddenError` | 40330 | 403 | 非作者且无 `*_any` 权限 |
| `PostNotFoundError` | 40430 | 404 | 不存在或已软删 |
| `SlugAlreadyTakenError` | 40930 | 409 | slug 唯一冲突（由仓储翻译而来） |

- [ ] **`value_objects.py`**

| 值对象 | 规则 |
| --- | --- |
| `PostTitle` | strip 后非空，长度 ≤ `POST_TITLE_MAX_LEN = 200` |
| `Slug` | `^[a-z0-9]+(?:-[a-z0-9]+)*$`，长度 ≤ `POST_SLUG_MAX_LEN = 120`；提供 `Slug.from_title(title)` 生成器 |
| `PostSummary` | 长度 ≤ `POST_SUMMARY_MAX_LEN = 500`，可为空 |
| `PostContent` | 非空；长度上限只做宽松兜底（`POST_CONTENT_MAX_LEN = 100_000`） |

长度常量放在本文件，**同时被 `PostModel` 的列宽引用**（与 `EMAIL_MAX_LEN` / `ROLE_CODE_MAX_LEN` 同一约定）。

- [ ] **`entities.py`** —— `Post` 聚合根 + `PostStatus` 常量类

`Post` 需要的业务方法（每个都是一条不变量，写在实体里而不是用例里）：

| 方法 | 固化什么 |
| --- | --- |
| `Post.create(author_id, title, ...)` | 唯一构造入口；id 由领域 `uuid4()` 生成；初始状态 `draft` |
| `update_content(title=..., content=..., ...)` | 用 `_UNSET` 哨兵实现 PATCH 语义（照抄 `domain/identity/entities.py::update_profile`） |
| `ensure_owned_by(user_id, *, has_override)` | **本步的核心**：作者本人或 `has_override=True` 才放行，否则 `PostForbiddenError` |
| `publish()` / `unpublish()` | 状态机；首次发布写 `published_at` |
| `soft_delete()` | 置 `deleted_at`；已删除再删不报错（幂等） |
| `ensure_not_deleted()` | 已软删视为不存在 |

- [ ] **`repositories.py`** —— `PostRepository(ABC)`

```
add(post) -> Post
get_by_id(post_id) -> Post | None          # 默认过滤 deleted_at IS NULL
get_by_slug(slug) -> Post | None
exists_slug(slug, *, exclude_id) -> bool   # 生成 slug 时重试用
list_published(offset, limit, *, tag_slug) -> list[Post]
count_published(*, tag_slug) -> int
list_by_author(author_id, offset, limit, *, status) -> list[Post]
count_by_author(author_id, *, status) -> int
update(post) -> None
```

接口参数一律用 **值对象**（`Slug`）而不是裸 `str`，与 `UserRepository.get_by_email(Email)` 保持一致。

> 本期 tags 若要落到 `post_tags`，在 `add` / `update` 上再加一个 `tags: frozenset[str]` 参数，或单独开 `TagRepository`。**建议后者**：让 `PostRepository` 保持单聚合职责。

### 3.2 `domain/access/entities.py`（改）

- [ ] `PermissionCode` 追加 `POST_UPDATE_ANY = "post:update_any"`、`POST_DELETE_ANY = "post:delete_any"`
- [ ] `PERMISSION_SPECS` 追加两条对应声明
- [ ] `ROLE_SPECS` 中 admin 用 `_ALL_PERMISSION_CODES`（自动包含），`author` **不加**这两个
- [ ] 顺手把 `PermissionCode` 里 `post:*` 的注释分组更新（现在写的是「文章」四个，变六个）

### 3.3 `application/blog/`

- [ ] **`dto.py`**（标准库 `dataclass`，不用 Pydantic，与 `application/identity/dto.py` 一致）

| 类型 | 字段要点 |
| --- | --- |
| `CreatePostCommand` | `author_id: UUID`、`title: str`、`content: str`、`summary: str \| None`、`slug: str \| None`、`tag_names: tuple[str, ...]` |
| `UpdatePostCommand` | `post_id`、`actor_id`、`actor_can_override: bool`、四个 `Unset` 字段 |
| `ChangePostStatusCommand` | `post_id`、`actor_id`、`actor_can_override` |
| `DeletePostCommand` | `post_id`、`actor_id`、`actor_can_override` |
| `ListPublishedPostsQuery` / `ListMyPostsQuery` | `offset`、`limit`、筛选 |
| `PostDTO.from_entity()` | 出参；**含 `author_id`**（前端要据此判断「显示不显示编辑按钮」） |
| `PostPageDTO` | `items: list[PostDTO]`、`total: int`、`offset`、`limit` |

- [ ] **`use_cases.py`** —— 6 个用例，**每个都在调 `ensure_owned_by` 之后才动数据**

| 用例 | 编排要点 |
| --- | --- |
| `CreatePostUseCase` | 生成/校验 slug（冲突则重试或抛 40930）→ `Post.create` → `add` |
| `GetPostBySlugUseCase` | 只返回 `published`；草稿对无权限者按 404 处理 |
| `ListPublishedPostsUseCase` | `published` + 未删除 + 分页 |
| `ListMyPostsUseCase` | 当前用户全部状态（含草稿），供「我的文章」页 |
| `UpdatePostUseCase` | 取 → `ensure_owned_by` → `update_content` → `update` |
| `PublishPostUseCase` / `UnpublishPostUseCase` | 取 → `ensure_owned_by` → 状态机 |
| `DeletePostUseCase` | 取 → `ensure_owned_by` → `soft_delete` |

> `actor_can_override` **由表现层算好传进来**（它知道该请求有没有 `post:update_any`），用例内部**不查仓储去判断权限**——授权是「这次请求允不允许」（表现层），用例只回答「给定一个用户和一份新文章，怎么改」。这条与 `ResetUserPasswordUseCase` 的既定做法一致。

### 3.4 `infrastructure/persistence/`

- [ ] **`models/post.py`**

| 列 | 类型 | 约束 |
| --- | --- | --- |
| `author_id` | `UUID` 外键 `users.id` | `index=True`，`ondelete="RESTRICT"` |
| `title` | `String(POST_TITLE_MAX_LEN)` | `nullable=False` |
| `slug` | `String(POST_SLUG_MAX_LEN)` | `unique=True, index=True` |
| `summary` / `content` | `String(500)` / `Text` | `content` 非空 |
| `cover_url` | `String(512)` | 可空 |
| `status` | `String(20)` | `index=True`，默认 `draft` |
| `published_at` | `DateTime(timezone=True)` | 可空 |
| `view_count` | `Integer` | 默认 0（本期只在详情页 +1，不做去重） |

继承 `IDMixin` + `TimestampMixin` + `SoftDeleteMixin`（**后者本期新建**，见下）：
- 构造时必须显式传 `id`（`insert_default` 约定，见 `persistence/base.py`）
- 手写 `__repr__`，别让 `content` 全文进日志（照抄 `UserModel` 排除 `password_hash` 的做法）

- [ ] **`base.py`（改）** —— 新增 `SoftDeleteMixin`：`deleted_at: Mapped[DeletedAt]`，`init=False`

现在 `DeletedAt` 别名已经存在但**没有被任何 Mixin 使用**，本步正好补上；comments（M5）也会复用。

- [ ] **`models/tag.py` + `models/post_tag.py`** —— `TagModel`（`name` / `slug` 双唯一）、`PostTagModel`（联合主键，继承**裸 `Base`**、无 `id`，与 `UserRoleModel` 一致）

- [ ] **`models/__init__.py`（改）** ⚠️ **漏了这步，`make revision` 会静默生成空迁移**

- [ ] **`mappers/post.py`** —— `to_model` / `apply_to_model`（仅可变字段）/ `to_entity`（逐字段显式搬运）

- [ ] **`repositories/post.py`** —— `SqlPostRepository`

| 要点 | 说明 |
| --- | --- |
| 软删过滤 | 所有查询带 `PostModel.deleted_at.is_(None)`，**不要**只在详情页加 |
| 唯一冲突翻译 | 捕获 `IntegrityError` → PG `23505` → 按约束名翻译成 `SlugAlreadyTakenError`（复用 `repositories/user.py` 的 `_sqlstate` / `_raise_translated` 写法，建议提到公共位置） |
| 排序 | `published_at desc nulls last, id desc` —— 同上，加 `id` 保证翻页稳定 |
| 只 `flush`，不 `commit` | 事务边界只属于 `core/database.py::get_db` |

### 3.5 `presentation/`

- [ ] **`api/v1/schemas/post.py`**

| Schema | 要点 |
| --- | --- |
| `CreatePostRequest` | `title` 1~200、`content` 非空、`slug` 可选且带正则、`tag_names` 默认 `[]` |
| `UpdatePostRequest` | **所有字段可选**（PATCH 语义）；路由里用 `model_dump(exclude_unset=True)` |
| `PostResponse` | `from_attributes=True`；**不含**软删标记等内部字段 |
| `PostPageResponse` | `items` / `total` / `offset` / `limit` |

- [ ] **`api/v1/endpoints/posts.py`**

| 方法 | 路径 | 守卫 |
| --- | --- | --- |
| GET | `/posts` | 无（公开） |
| GET | `/posts/mine` | `post:create`（能在写文章就有「我的文章」） |
| GET | `/posts/{slug}` | 无（公开） |
| POST | `/posts` | `post:create` |
| PATCH | `/posts/{post_id}` | `post:update`，并计算 `actor_can_override` |
| POST | `/posts/{post_id}/publish` | `post:publish` |
| POST | `/posts/{post_id}/unpublish` | `post:publish` |
| DELETE | `/posts/{post_id}` | `post:delete` |

> ⚠️ **路由顺序陷阱**：`/posts/mine` 必须声明在 `/posts/{slug}` **之前**，否则 `mine` 会被当成 slug 匹配掉，表现为「我的文章」永远 404。这是 FastAPI 按注册顺序匹配的必然结果，不是 bug。

- [ ] **`api/v1/router.py`（改）** —— `include_router(posts_router, prefix="/posts", tags=["posts"])`

- [ ] **`presentation/dependencies.py`（改）** —— 加 `get_post_repository` + 7 个用例工厂；建议同时加一个 `get_optional_current_user`（读接口要判断「是不是作者本人」时用，未登录返回 `None` 而不抛 401）

- [ ] **翻页参数** —— 复用 `agent_web_shared.normalize_pagination`（`DEFAULT_LIMIT=20` / `MAX_LIMIT=100`），不要手写 `min/max`

### 3.6 迁移

- [ ] 先改完 `models/__init__.py`，**再**执行：

```
cd apps/backend
make revision m="add blog posts tags"
make migrate
```

- [ ] **人工校对生成的迁移**（自动生成不会替你想这些）：
  - `tags.name` / `tags.slug` / `posts.slug` 的 `unique` 是否都在
  - `posts.author_id` 外键的 `ondelete` 是否符合预期
  - `posts.status` / `posts.published_at` 是否建了索引
  - 降级路径 `downgrade()` 是否按 `post_tags → tags → posts` 逆序 drop

### 3.7 后端测试

- [ ] **`tests/unit/test_post.py`**（纯领域，不碰数据库）

| 用例 | 断言 |
| --- | --- |
| 标题空白 / 超长 | `InvalidTitleError` |
| `Slug.from_title("Hello, World!")` | 得到 `hello-world` |
| `ensure_owned_by(别人, has_override=False)` | `PostForbiddenError` |
| `ensure_owned_by(别人, has_override=True)` | 通过 |
| `draft → unpublish` | `InvalidPostStatusTransitionError` |
| 首次 publish | `published_at` 被写 |
| publish → unpublish → publish | `published_at` **不变** |
| `soft_delete()` 两次 | 幂等，不抛 |

- [ ] **`tests/integration/test_posts_api.py`**

| 用例 | 断言 |
| --- | --- |
| author 建草稿 | 201，`status=draft` |
| 草稿不出现在 `GET /posts` | `total` 不含它 |
| publish 后出现在列表 | 且 `published_at` 有值 |
| **author A 改 author B 的文章** | **403 + code 40330**（PLAN 4.6 硬验收） |
| **admin 改 author B 的文章** | **200**（验证 `post:update_any` 生效） |
| reader 建文章 | 403 + code 40320 |
| 软删后再 `GET /posts/{slug}` | 404 |
| 软删后列表不含 | `total` 减少 |
| slug 重复 | 409 + code 40930 |
| `/posts/mine` 在 `/posts/{slug}` 之前注册 | 返回自己的草稿列表而非 404 |
| 分页 | `offset=0,limit=2` 与 `offset=2,limit=2` 结果不重叠 |

> ⚠️ 集成测试记得**依赖 `tests/integration/conftest.py::seeded_access_catalog`**（autouse）。`ASGITransport` 不跑 lifespan，缺了它 `post:*` 权限不存在，新建文章会因为找不到角色/权限而拿到意料外的错误码。

---

## 4. 前端任务清单

### 4.1 依赖

- [ ] 新增 Markdown 渲染。**推荐 `react-markdown` + `remark-gfm`**（默认不解析原始 HTML，天然规避 XSS）。
  - 若坚持 `marked`（体积更小），**必须同时装 `dompurify`** 并对输出做 `sanitize`——文章内容虽是自家用户写的，但 `author` 角色是「任何注册用户可被授予」的，不能当成可信输入。

```
& "$env:APPDATA\npm\pnpm.cmd" --filter frontend add react-markdown remark-gfm
```

### 4.2 `src/features/access/permissions.ts`（先改这个）

- [ ] 补上权限码常量（**必须与后端 `PermissionCode` 逐字一致**）：

```ts
POST_CREATE: 'post:create',
POST_UPDATE: 'post:update',
POST_PUBLISH: 'post:publish',
POST_DELETE: 'post:delete',
POST_UPDATE_ANY: 'post:update_any',
POST_DELETE_ANY: 'post:delete_any',
```

- [ ] 加一个 `canEditPost(codes, post, currentUserId)` 帮助函数（放在 `features/post/permissions.ts` 更合适），把「作者本人 OR 有 `*_any`」这条规则**和按钮显隐集中在一处**——不要在每个页面里各写一遍 `post.author_id === me.id || hasPermission(...)`。

### 4.3 `src/features/post/`

- [ ] **`types.ts`** —— `PostStatus`、`Post`、`PostPage`，字段与 `PostResponse` 对齐（TS 侧用 `snake_case`，与既有 `features/access/types.ts` 保持一致）
- [ ] **`api.ts`** —— 8 个函数 + `postKeys` 工厂（照抄 `features/access/api.ts` 的结构：`api.ts` 只拼路径定类型、`hooks.ts` 管缓存、`permissions.ts` 管判断）
- [ ] **`hooks.ts`**

| Hook | 缓存策略 |
| --- | --- |
| `usePostsQuery(offset, limit)` | `placeholderData: keepPreviousData`（翻页不闪） |
| `usePostQuery(slug)` | 详情，`staleTime` 短一点 |
| `useMyPostsQuery(offset, limit)` | 登录态数据 |
| `useCreatePostMutation` | 成功后失效列表 + 跳转到编辑页 |
| `useUpdatePostMutation` | 成功后失效**详情**与**列表**（`postKeys.detail(slug)` + `postKeys.lists()`） |
| `usePublishPostMutation` / `useUnpublishPostMutation` | 失效详情 + 列表 |
| `useDeletePostMutation` | 成功后跳回列表 |

- [ ] **`PostListPage.tsx`** —— 仅 `published`；卡片显示标题/摘要/作者/`published_at`；分页按钮复用 `UserManagementPage` 的分页写法
- [ ] **`PostDetailPage.tsx`** —— Markdown 渲染 + 「编辑 / 发布 / 下架 / 删除」按钮（按 `canEditPost` 显隐）
- [ ] **`MyPostsPage.tsx`** —— 自己的全部状态（草稿置顶或分组），状态徽章
- [ ] **`editor/PostEditorPage.tsx`** —— 新建与编辑**同一个组件**（根据路由有无 id 分流）；字段：标题、slug（可留空自动生成）、摘要、正文、标签；保存按钮要区分「保存草稿」与「保存并发布」
- [ ] **`PostListPage.test.tsx`** —— 至少覆盖：空列表文案、加载态、点「写文章」入口的权限显隐

### 4.4 `src/router.tsx`（改）

```
/posts             → PostListPage        （在 AppLayout children 内）
/posts/:slug       → PostDetailPage
/my/posts          → MyPostsPage
/editor            → PostEditorPage      （新建）  需 post:create
/editor/:postId    → PostEditorPage      （编辑）  需 post:update
```

「写文章」「我的文章」用 **pathless 路由 + `RequirePermission`** 包住（照抄 `admin/users` 的写法），理由与那里相同：守卫要先于页面挂载，避免无权限的人白打一次接口。

### 4.5 `src/layouts/AppLayout.tsx`（改）

- [ ] 导航加「文章」（`BASE_NAV_ITEMS`，所有人可见）
- [ ] 加「我的文章」「写文章」到权限项列表（`POST_CREATE`）
- [ ] `HomePage` 顺手改成文章列表入口或直接 `Navigate to="/posts"`（可选，看你想不想保留首页）

### 4.6 收尾

- [ ] `PostEditorPage` 的表单错误用后端返回的 `ApiError.field` 挂到对应输入框（`lib/api.ts` 已经提供 `field` getter，`components/Field.tsx` 已就位）
- [ ] 运行 `make format`（根目录）：新增的 `.ts/.tsx` 会被 prettier 按 `endOfLine: "lf"` 重写

---

## 5. 验收清单（对齐 PLAN 4.6 + 第八章 DoD）

**功能（PLAN 4.6 原文）**

---

## 6. 执行结果（已完成）

本节记录**实际落地时与上面方案的差异**，方案本身不改，方便对照。

### 后端

- 已按方案实现全部四层 + 迁移（`73556e70e308_add_blog_tables.py`，`down_revision = 0b3a7e62ba2f`）。
- 测试：`tests/unit/test_post.py`（46）+ `tests/integration/test_posts_api.py`（32），
  全量 **160 passed**；`ruff check` / `ruff format --check` 干净。
- **§3.4 的结论是错的**：`SoftDeleteMixin` 不需要新建，`infrastructure/persistence/base.py` 里已经有了。
- 权限方案落地为「守卫 + 实体」两次判断：
  `require_permission(POST_UPDATE)`（40320）→ `Post.ensure_owned_by(actor, has_override=...)`
  （40330）。`post:update_any` / `post:delete_any` 只给 admin，作者**不**持有——
  否则「作者只能改自己的」这条约束会被自己手里的权限废掉。
- 未登录也能读：`GET /posts`、`GET /posts/{slug}` 用 `OptionalCurrentUser`。
  别人的**草稿**回 404（存在性也是隐私），已发布但不是自己的文章回 403。
- 修了一个方案没写到的坑：`UpdatePostUseCase` 直接用 `command.tag_names` 迭代，
  前端清空标签时提交的 `{"tag_names": null}` 会 `TypeError` → **500**。
  现在统一 `command.tag_names or ()`，与 `summary: null` 表示「清空」同一套语义。
- `list_published` 曾经算出了标签筛选条件却没拼进 SQL（表现为「total 是 3，却返回 20 条」），已修。

### 前端（与 §4 的差异）

- §4.5 说的 `AppLayout` 改造 → 实际**把布局拆成了两层**，因为多了「公开阅读区」：
  - `layouts/SiteHeader.tsx`（新）：页头，按登录态决定导航项，并**按登录态开合查询**；
  - `layouts/SiteLayout.tsx`（`AppLayout` 改名而来）：页头 + `Outlet`，公开区与受保护区**共用同一个**。
  两套布局会让页头长出两份略有差别的实现，而路由层的 `RequireAuth` 才是
  「要不要先去登录」该待的地方。
- 公开区的关键实现不是「不套守卫」，而是**页头把两个登录相关请求关掉**：
  `useMeQuery({ enabled: Boolean(auth.token) })` + `useMyAccessQuery({ enabled: ... })`。
  这两个接口未登录必然 401，而 401 会清登录态——不关掉就是
  「看别人的文章顺手把自己登出了」。退出按钮也只 `clearAuth()`、不跳转。
- §4.4 的路由有两处修正：
  - 编辑路由的路径参数是 **slug**（`/editor/:slug`）而不是 `postId`：能写进 URL、
    能刷新、能分享，而 `postId` 对外没有意义；
  - 「写文章」的守卫用**「满足其一」**（`RequirePermission` 现在接受权限数组）：
    `post:create` 或 `post:update_any`，与页头里 `canCreatePost` 的口径必须一致，
    否则会出现「导航有入口、点进去说没权限」。
- 「我的文章」路由只要求登录、不挂权限码：那里的所有者就是调用者本人，
  归属是比权限码更强的约束。接口路径是 `/me/posts`，前端路由是 `/my/posts`，**故意不同名**。
- §4.6 的两条都已落地：`ApiError.field` → `FIELD_MAP` 映射到具体输入框；
  新增文件已按 `endOfLine: "lf"` 重排。
- 测试：`features/post/PostListPage.test.tsx` 用「**游客没有发出 `/auth/me` 请求**」
  来钉住公开阅读这条决定（只断言「文章显示出来了」测不出上面那个 401 坑）。
  前端全量 **30 passed / 8 files**，`tsc -b` 与 eslint 均干净。

### 还没做

- 单篇详情页的测试、编辑器表单的测试（`PostListPage.test.tsx` 是这一批里唯一的前端新测试）。
- `HomePage` 仍然是占位页（§4.5 标为可选，未动）。
- 评论、点赞等互动（M5）——**随后已做完，见 §6.5**。


- [ ] 非作者改文章 → **403**
- [ ] 列表分页正确（两页结果不重叠、`total` 准确）
- [ ] 软删除的文章不出现在任何公开列表与详情

**分层（DoD）**

- [ ] `domain/blog/` 不 import FastAPI / SQLAlchemy / Pydantic
- [ ] `PostRepository` 接口在 `domain`，`SqlPostRepository` 在 `infrastructure`
- [ ] 仓储内**没有** `commit()`，事务边界只在 `core/database.py::get_db`
- [ ] 所有错误经 `core/exceptions.py` 统一成 `{code,message,data}`
- [ ] `PostResponse` 不含 `deleted_at` 等内部字段
- [ ] 新模型已加入 `infrastructure/persistence/models/__init__.py`，迁移可自动生成
- [ ] 权限码在「后端 `PermissionCode` / 种子声明区 / 前端 `PERMISSION`」三处一致

**命令全绿**

```
make lint
make test
```

---

## 6.5 M5 评论点赞执行结果（已完成）

M5 在本文件（M4 方案）验收完之后紧接着做掉了，两端都已落地并浏览器实测。原 PLAN 5.x 有两处
**被实际推翻**，记在这里，免得后来人照着旧措辞改回去。

### 后端

- 上下文 `interaction` 依赖 `blog`（要读文章可见性）但**不合并**：`domain/interaction/*` 只 import
  `app.domain.blog.entities.PostStatus` 与 `PostNotFoundError`，反向不存在。
- **没有 `Like` 实体**（刻意）：点赞没有行为、没有生命周期，唯一规则是
  `unique(user_id, target_type, target_id)`——那是数据库的活。领域层只有值对象 `LikeTargetType`。
- 文件：`domain/interaction/{__init__,exceptions,value_objects,entities,repositories}.py`、
  `application/interaction/{__init__,dto,use_cases}.py`、
  `infrastructure/persistence/{models/{comment,like}.py, mappers/comment.py, repositories/interaction.py}`、
  `presentation/api/v1/{schemas/{comment,like}.py, endpoints/{comments,likes}.py}`、
  迁移 `db936358c4a8_add_interaction_tables.py`（已 apply）。
- 端点：`GET|POST /api/v1/posts/{post_id}/comments`、`DELETE /api/v1/comments/{comment_id}`（204）、
  `POST /api/v1/likes/toggle`、`GET /api/v1/posts/{post_id}/interactions`（**新增，PLAN 里没有**）。
  评论一律用 `post_id` 而不是 slug：slug 可改、id 不会，且这样与 `likes/toggle` 的 `target_id` 对齐。
- **无冗余计数字段**：`like_count` / `comment_count` 一律实时聚合（`count_many` / `count_by_posts`）。
  软删除评论与点赞是两张表，冗余列要靠跨表事务保一致，成本远大于一次 COUNT。
- 软删除 = 墓碑：撤回后 `public_content` 为空串、`is_deleted = true`，前端灰字显示「该评论已被作者撤回」；
  但**回复关系仍然照常显示**——撤回隐藏的是内容，不是「谁回复了谁」。
- 错误码：40040 正文非法 / 40041 点赞目标类型非法 / 40340 无权删他人评论 / 40440 评论不存在 /
  40441 互动目标不存在 / 40940 互动已关闭。删除两次回 **404 + 40440**（不是再回 204），与 M4 的重复
  `DELETE /posts/{id}` 一致：领域不变量是「已撤回的评论对所有入口等同于不存在」。
- 测试：`tests/unit/test_comment.py` + `tests/integration/test_interaction_api.py`，
  全量 **239 passed**，`ruff check` / `ruff format` 干净。

### ★ 推翻一：评论树不是两层，是任意深度

原 PLAN 5.1 写的是「嵌套层级限制」，落地时也确实按两层做过（`COMMENT_TREE_DEPTH = 2`，
回复「回复的回复」时用 `Comment.thread_root_id` 把父节点折算到根）。**这个设计被否决并已拆除**：

- `comments.parent_id` 现在存的是**真正被回复的那条评论**，不做任何折算。旧做法是**不可逆**的
  ——信息一旦折掉，就再也恢复不出真实的父节点。
- 唯一的结构不变量是**父链无环**，由时间顺序天然保证（父必定先于子存在）。
- 仓储换成 `list_descendants(root_ids)`（列清单递归 CTE，一次批量取全部后代）与
  `_visible_root_cte`（递归时逐层携带 `node_id`；只带锚点 id 会把根解析成叶子，计数静默错）。
- **缩进几层是界面的事**：前端第二层起的评论全部落在**同一条竖线**上
  （`depth === 1 ? 'border-l-2 pl-4' : 'mt-3'`）。用层数乘倍数算 `paddingLeft` 是这类需求的经典 bug。
- 已删除的符号：`Comment.thread_root_id`、`COMMENT_TREE_DEPTH`。别再按 PLAN 5.1 的旧措辞理解这个上下文。
- `GET comments` 的 `total` 仍是**根评论数**（界面上的「N 段对话」），不是总条数；
  总条数走文章详情里的 `comment_count`。

### ★ 推翻二：作者名由后端解析，前端不查用户

「用户 A 回复 B」需要名字，但 `GET /users/{id}` 要 `user:list`（admin 权限），匿名读者根本调不动，
逐条调还会把 N+1 搬进浏览器，而且每个请求都要重新鉴权。因此：

- `CommentResponse` 增加 `author_display_name` / `parent_author_display_name`
  （`display_name` 优先，回落 `username`；根评论的父名字为 `null`）；
- `UserRepository` 增加**批量**的 `get_by_ids(ids)`（一条 `IN (...)`；空入参直接返回 `{}`，
  因为 `IN ()` 在部分驱动下是语法错误）；
- 前端测试钉住「渲染评论时没有发出任何 `/users/` 请求」。

### 前端

- 文件：`features/comment/{types,api,hooks,permissions,tree}.ts`、
  `features/comment/{CommentTree,CommentItem,CommentForm}.tsx`、
  `features/like/{LikeButton,PostInteractionBar}.tsx`、`features/post/PostDetailPage.tsx`。
- `tree.ts::patchNode` 递归 `replies` 不设层数上限，发表/撤回后就地改 React Query 缓存，不整棵树重拉。
- `CommentItem` 的 `depth` prop 语义是「这是第几层」，**不是缩进倍数**，递归时传 `depth + 1`
  （旧代码的 `Math.min(depth + 1, 1)` 是两层树时代的产物，必须一起删掉）。
- 测试：全量 **44 passed / 10 files**，`tsc -b` / eslint / prettier 全干净。
- 浏览器实测：造了一条 **6 层**的评论链，第一层 `x=95`、第 2~6 层全部 `x=113`（同一条竖线），
  每层头部都显示「用户 X 回复 Y」，并从界面在第五层下成功回复出第六层（评论数 5 → 6）。

### 还没做

- M6 AI Agent（唯一需要外部 LLM key 的模块）。

---

## 7. 建议执行顺序

严格按依赖倒序推进，每步都能独立验证：

| # | 步骤 | 验证方式 |
| --- | --- | --- |
| 1 | 后端 `domain/blog/` 四文件 | `pytest tests/unit/test_post.py`（先写测试） |
| 2 | 后端 `domain/access/entities.py` 加两个权限码 | `pytest tests/unit/test_access.py` 仍绿 |
| 3 | 后端 `application/blog/` | 单测用内存替身（继承 `PostRepository` 的 Fake 实现） |
| 4 | 后端 `infrastructure/persistence/` 三件套 + `base.py` 的 `SoftDeleteMixin` | `make revision` 生成迁移并**人工校对** |
| 5 | `make migrate` + 重启后端 | 看日志确认 `seed` 补建了 `post:update_any` / `post:delete_any` |
| 6 | 后端 `presentation/` 四文件 | Swagger 手测 8 个端点；`pytest tests/integration/test_posts_api.py` |
| 7 | 前端 `permissions.ts` + `features/post/{types,api,hooks}.ts` | 页面能拉到列表 |
| 8 | 前端 4 个页面 + 路由 + 导航 | 手动跑完「写 → 存草稿 → 发布 → 下架 → 删」 |
| 9 | 前端组件测试 | `pnpm --filter frontend test` |
| 10 | `make lint && make test` | 全绿后提交 |

建议提交切分（`<type>(<scope>): <subject>`）：

```
feat(blog): 领域层文章实体与状态机
feat(blog): 文章仓储与迁移
feat(access): 新增 post:update_any / post:delete_any 权限
feat(blog): 文章读写接口与行级归属校验
feat(post): 文章列表、详情与编辑器页面
```

---

## 8. 风险与待确认

| # | 事项 | 影响 | 建议 |
| --- | --- | --- | --- |
| 1 | **是否加 `post:update_any` / `post:delete_any`** | 不加则「admin 可管所有文章」与「author 只能改自己」无法同时成立 | 按 2.1 方案执行；如你希望 admin 与 author 用**同一套归属规则**（即 admin 也只能改自己的），告诉我，我会省掉这两个权限码 |
| 2 | 文章页是否要求登录（2.4） | 影响 `AppLayout` 是否本步重构 | 默认**保持登录可见**，公开访问留 TODO |
| 3 | 标签是否本期就落 `post_tags` | 涉及多写两张表和一次迁移 | 建议**建表但只做「随文章提交自动创建」**，删掉独立标签管理；若想再压缩范围，可先只存 `tag_names` 到 JSON 列之后再迁——**不推荐**，迁移成本更高 |
| 4 | `view_count` 计数方式 | 详情页每刷 +1 会让它变成浏览量而非访客数 | 本期接受「每次 GET 详情 +1」，在字段注释里写明 |
| 5 | 富文本 / 图片上传 | 会让本期范围膨胀 | 明确不做，封面只收外链 URL |
| 6 | `post:update` 语义重叠 | 前端按钮显隐若不抽 `canEditPost`，容易出现「按钮给了、一点 403」 | 见 4.2 的建议 |

---

## 9. 一句话总结

**下一步 = 把 `blog` 上下文按 `identity` 的结构补齐四层（后端），再把 `features/post/` 按 `features/access/` 的结构补齐页面（前端）。**
本步唯一的新问题是**行级归属**：用「领域方法 `ensure_owned_by` + 两个只给 admin 的 `*_any` 权限码」解决，判定顺序为「RBAC 守卫 → 是否作者本人 → 是否有 override 权限」。
