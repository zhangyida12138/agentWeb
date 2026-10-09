# AgentWeb 博客系统 · 开发计划表

> 目标：在本 monorepo 中，从零构建一个 **带 AI Agent 的完整博客网站**。
> 分层规范与代码范式见根目录 [backend.md](./backend.md)（DDD 四层 + core 内核）。
> 本文是**可执行的任务表**：按里程碑顺序逐项勾选推进，每项都有明确的产出文件与验收标准。

---

## 一、项目目标与功能范围

| 编号 | 功能域 | 具体要求 |
| --- | --- | --- |
| F1 | 用户功能 | 注册、登录、退出、查看/编辑个人信息、修改密码 |
| F2 | 权限功能 | RBAC：角色（admin/author/reader）× 权限；接口级守卫；管理后台 |
| F3 | 评论点赞 | 文章评论（支持嵌套回复）、删除评论；文章/评论点赞与取消 |
| F4 | 发布删除 | 文章新建/编辑/发布/下架/软删除；草稿与已发布状态机 |
| F5 | AI Agent | 会话管理 + 流式对话（SSE/WebSocket）；写作助手/问答 |

---

## 二、技术栈（沿用仓库现状）

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12 · uv · FastAPI · SQLAlchemy 2.0(async) · Alembic · PostgreSQL 16 · Pydantic v2 · pytest |
| 后端新增依赖 | `python-jose[cryptography]` 或 `pyjwt`（JWT）、`passlib[bcrypt]` 或 `bcrypt`、`loguru`（日志）、`jinja2`（提示词）、`openai`（LLM 客户端）、`sse-starlette`（可选） |
| 前端 | Node 20 · pnpm · Vite · React 19 · TypeScript · React Router 7 · TanStack Query v5 · UnoCSS · Vitest |
| 前端新增依赖 | `marked` 或 `react-markdown`（Markdown 渲染）、`@tanstack/react-form` 或 `react-hook-form`（表单，可选）、`zustand`（登录态，可选） |
| 工程化 | GNU Make · Docker Compose · ESLint · Prettier · ruff · husky + lint-staged |

---

## 三、架构与目录约定

### 3.1 后端 DDD 分层（每个限界上下文一套四层）

```
apps/backend/src/app/
├── main.py
├── core/                        # 配置 / 数据库会话 / 日志 / 中间件 / 全局异常
├── domain/<context>/            # 实体、值对象、仓储接口、领域异常（无框架依赖）
├── application/<context>/       # 用例、DTO
├── infrastructure/persistence/  # models / mappers / repositories
└── presentation/api/v1/         # endpoints / schemas + dependencies.py
```

### 3.2 限界上下文划分

| 上下文 | 职责 | 核心概念 |
| --- | --- | --- |
| `identity` | 用户与认证 | User、Credential、Email |
| `access` | 权限 | Role、Permission、UserRole |
| `blog` | 文章 | Post、Tag、PostStatus |
| `interaction` | 互动 | Comment、Like |
| `agent` | AI 助手 | Conversation、Message |

### 3.3 前端目录约定

```
apps/frontend/src/
├── main.tsx
├── router.tsx
├── lib/            # query-client、api 客户端（统一信封解析 + token 注入）
├── stores/         # 登录态
├── layouts/        # 布局
├── pages/          # 页面
├── components/     # 通用组件
├── features/       # 按功能域组织（post/comment/agent/auth）
└── test/           # 测试 setup
```

---

## 四、数据库表设计（草稿，随开发微调）

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `users` | id, email(uniq), username(uniq), password_hash, display_name, avatar_url, bio, is_active, created_at, updated_at | 用户 |
| `roles` | id, code(uniq), name, description | 角色 admin/author/reader |
| `permissions` | id, code(uniq), name, description | 权限点，如 `post:create` |
| `user_roles` | user_id, role_id (PK 联合) | 用户↔角色 |
| `role_permissions` | role_id, permission_id (PK 联合) | 角色↔权限 |
| `posts` | id, author_id(FK), title, slug(uniq), summary, content, cover_url, status, published_at, view_count, deleted_at, created_at, updated_at | 文章（软删除） |
| `tags` | id, name(uniq), slug(uniq) | 标签 |
| `post_tags` | post_id, tag_id (PK 联合) | 文章↔标签 |
| `comments` | id, post_id(FK), author_id(FK), parent_id(FK 自引用), content, deleted_at, created_at, updated_at | 评论（嵌套 + 软删除） |
| `likes` | id, user_id, target_type(post/comment), target_id, created_at，`unique(user_id,target_type,target_id)` | 点赞 |
| `conversations` | id, user_id(FK), title, created_at, updated_at | Agent 会话 |
| `messages` | id, conversation_id(FK), role(user/assistant), content, created_at | 会话消息 |

---

## 五、API 设计概览

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | 否 | 注册 |
| POST | `/api/v1/auth/login` | 否 | 登录，返回 token |
| GET | `/api/v1/auth/me` | 是 | 当前用户 |
| PATCH | `/api/v1/auth/me` | 是 | 修改资料 |
| POST | `/api/v1/auth/change-password` | 是 | 修改密码 |
| GET | `/api/v1/users` | admin | 用户列表 |
| PATCH | `/api/v1/users/{id}/roles` | admin | 分配角色 |
| GET | `/api/v1/roles` `/permissions` | admin | 角色/权限列表 |
| GET | `/api/v1/posts` | 否 | 文章列表（分页/标签/状态筛选） |
| GET | `/api/v1/posts/{slug}` | 否 | 文章详情 |
| POST | `/api/v1/posts` | post:create | 新建（草稿） |
| PATCH | `/api/v1/posts/{id}` | 作者/管理员 | 编辑 |
| POST | `/api/v1/posts/{id}/publish` | 作者/管理员 | 发布 |
| POST | `/api/v1/posts/{id}/unpublish` | 作者/管理员 | 下架 |
| DELETE | `/api/v1/posts/{id}` | 作者/管理员 | 软删除 |
| GET | `/api/v1/posts/{id}/comments` | 否 | 评论树 |
| POST | `/api/v1/posts/{id}/comments` | 是 | 发表评论/回复 |
| DELETE | `/api/v1/comments/{id}` | 作者/管理员 | 删除评论 |
| POST | `/api/v1/likes/toggle` | 是 | 点赞/取消（target_type + target_id） |
| GET | `/api/v1/agent/conversations` | 是 | 会话列表 |
| POST | `/api/v1/agent/conversations` | 是 | 新建会话 |
| GET | `/api/v1/agent/conversations/{id}/messages` | 是 | 历史消息 |
| GET | `/api/v1/agent/chat` (SSE) | 是 | 流式对话 |
| WS | `/api/v1/agent/ws` | 是(token query) | 双向流式对话 |

---

## 六、里程碑总览

| 里程碑 | 阶段 | 目标 | 前置依赖 |
| --- | --- | --- | --- |
| M0 | P0 环境与工程基座 | 一键起 DB + 前后端空壳跑通 | — |
| M1 | P1 后端内核基建 | core + main + 统一响应/异常/日志 + health | M0 |
| M2 | P2 身份与认证 | 注册/登录/JWT/bcrypt/当前用户 | M1 |
| M3 | P3 权限 RBAC | 角色/权限/守卫/种子数据 | M2 |
| M4 | P4 博客文章 | 文章 CRUD + 发布/删除状态机 | M2 |
| M5 | P5 互动 | 评论（嵌套）+ 点赞 | M4 |
| M6 | P6 Agent | 会话 + 流式对话 | M2 |
| M7 | P7 前端基座 | 路由/Query/ApiClient/登录态 | M1 |
| M8 | P8 前端业务页 | 文章/评论/点赞/Agent/后台 | M4,M5,M6,M7 |
| M9 | P9 测试与质量 | 单测+集成+覆盖率 | 各阶段 |
| M10 | P10 部署交付 | Docker + CI | 全部 |

---

## 七、阶段任务明细

> 勾选框：`[ ]` 未开始 · `[x]` 已完成。每个阶段完成后先 `make lint && make test` 再进入下一阶段。

### P0 · 环境与工程基座（M0）

| # | 任务 | 产出 | 验收标准 |
| --- | --- | --- | --- |
| 0.1 | 校验 Docker DB 可启动 | `docker-compose.yml` | `make db-up` 后 `docker compose ps` 显示 healthy |
| 0.2 | 校验环境变量模板 | 根 `.env.example`、`apps/backend/.env.example` | 按模板生成 `.env` 后后端能读到配置 |
| 0.3 | 校验 Makefile 命令 | 根 `Makefile` | `make install` 成功 |
| 0.4 | 校验前后端空壳可启动 | — | `make dev` 前端 5173、后端 8000 可访问 |

### P1 · 后端内核基建（M1）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 1.1 | 配置中心 | `core/config.py` | `get_settings()` 单例；含 app/env/debug/cors/db/jwt/llm 字段 |
| 1.2 | 数据库引擎与会话 | `core/database.py` | `get_session()` 依赖：异常回滚/正常提交/必定关闭 |
| 1.3 | 日志 | `core/logging.py` | 结构化输出，带 `request_id`（ContextVar） |
| 1.4 | 异常基类与全局处理器 | `core/exceptions.py` | `DomainError`/`ApplicationError` + 错误码映射，响应为 `{code,message,data}` |
| 1.5 | 中间件 | `core/middleware/{process_time,logging,cors,response}.py`、`__init__.py` | 列表化注册；统一响应信封；CORS 生效 |
| 1.6 | ORM 基类 | `infrastructure/persistence/base.py` | `Base` + `IDMixin` + `TimestampMixin` |
| 1.7 | 路由与健康检查 | `presentation/api/v1/{router.py,endpoints/health.py}` | `GET /api/v1/health` 返回统一信封 |
| 1.8 | 应用工厂 | `main.py` | 注册顺序：日志→中间件→异常→路由；lifespan 就绪 |
| 1.9 | Alembic 对接 | `migrations/env.py` | `target_metadata = Base.metadata`；`make revision` 可用 |
| 1.10 | 依赖与开关 | `pyproject.toml`、`.env.example` | 新增依赖安装；`make test` 通过（空测试集） |

### P2 · 身份与认证（M2）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 2.1 | 领域：实体/值对象/仓储接口/异常 | `domain/identity/{entities,value_objects,repositories,exceptions}.py` | Email 归一化+校验；User 实体含 `change_password` |
| 2.2 | 安全工具（bcrypt + JWT） | `packages/backend/shared/.../security.py` | `hash/verify_password`、`create/decode_token` |
| 2.3 | 应用：用例 + DTO | `application/identity/{use_cases,dto}.py` | Register/Login/GetMe/UpdateProfile/ChangePassword |
| 2.4 | 基础设施：模型/Mapper/仓储 | `infrastructure/persistence/{models/user.py,mappers/user.py,repositories/user.py}` | `models/__init__.py` 注册模型 |
| 2.5 | 首个迁移 | `migrations/versions/xxxx_init_identity.py` | `make migrate` 建出 `users` 表 |
| 2.6 | 表现层：schema + 路由 + 依赖 | `presentation/api/v1/{schemas/auth.py,endpoints/auth.py}`、`presentation/dependencies.py` | `get_current_user` 守卫可用 |
| 2.7 | 集成测试 | `tests/integration/test_auth_api.py` | 注册→登录→/me；错误密码 401；重复邮箱 409 |

### P3 · 权限 RBAC（M3）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 3.1 | 领域：Role/Permission/关联 | `domain/access/{entities,repositories,exceptions}.py` | 权限点常量集中定义 |
| 3.2 | 基础设施：4 张表模型 + 仓储 | `infrastructure/persistence/models/{role,permission,user_role,role_permission}.py`、`repositories/access.py` | 联合主键正确 |
| 3.3 | 应用：授权用例 | `application/access/use_cases.py` | 分配角色、校验权限、列出角色/权限 |
| 3.4 | 守卫依赖 | `presentation/dependencies.py` | `require_permission("post:create")` 生成依赖 |
| 3.5 | 种子数据 | `core/seed.py`（lifespan 幂等写入） | 启动后 admin/author/reader 及权限就绪；可重复执行 |
| 3.6 | 管理接口 | `presentation/api/v1/endpoints/{users,roles}.py` | 非 admin 访问 403；admin 200 |
| 3.7 | 测试 | `tests/unit/test_access.py`、`tests/integration/test_rbac_api.py` | 权限矩阵用例通过 |

### P4 · 博客文章（M4）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 4.1 | 领域：Post/Tag/状态机 | `domain/blog/{entities,value_objects,repositories,exceptions}.py` | draft→published→archived；仅作者/管理员可改删 |
| 4.2 | 基础设施：模型/Mapper/仓储 | `infrastructure/persistence/{models/post.py,models/tag.py,mappers/post.py,repositories/post.py}` | 软删除过滤；分页查询 |
| 4.3 | 应用：用例 | `application/blog/use_cases.py` | Create/Update/Publish/Unpublish/Delete/Get/List |
| 4.4 | 表现层：schema + 路由 | `presentation/api/v1/{schemas/post.py,endpoints/posts.py}` | 公开读、授权写；slug 唯一处理 |
| 4.5 | 迁移 | `migrations/versions/xxxx_blog.py` | 建出 posts/tags/post_tags |
| 4.6 | 测试 | `tests/unit/test_post.py`、`tests/integration/test_posts_api.py` | 非作者 403；列表分页；软删不出现 |

### P5 · 评论与点赞（M5）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 5.1 | 领域：Comment/Like 规则 | `domain/interaction/{entities,repositories,exceptions}.py` | 嵌套层级限制；点赞幂等 |
| 5.2 | 基础设施：模型/仓储 | `infrastructure/persistence/{models/comment.py,models/like.py,repositories/interaction.py}` | `unique(user_id,target_type,target_id)` |
| 5.3 | 应用：用例 | `application/interaction/use_cases.py` | 发表/删除评论；评论树组装；ToggleLike；计数 |
| 5.4 | 表现层：路由 | `presentation/api/v1/endpoints/{comments.py,likes.py}` | 评论树返回；点赞返回最新计数 |
| 5.5 | 迁移 | `migrations/versions/xxxx_interaction.py` | 建出 comments/likes |
| 5.6 | 测试 | `tests/integration/test_interaction_api.py` | 重复点赞不重复计数；回复归属正确 |

### P6 · AI Agent（M6）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 6.1 | 领域：Conversation/Message | `domain/agent/{entities,repositories,exceptions}.py` | 会话归属校验 |
| 6.2 | 基础设施：LLM 适配器 + 提示词 | `infrastructure/adapters/llm.py`、`infrastructure/adapters/templates/*.j2` | 可配置 base_url/model/key；Jinja2 模板 |
| 6.3 | 基础设施：模型/仓储 | `infrastructure/persistence/{models/conversation.py,models/message.py,repositories/agent.py}` | 消息按时间序 |
| 6.4 | 应用：流式编排 | `application/agent/use_cases.py` | 慢操作前 `commit+close` 归还连接；结束后 `merge` 落库 |
| 6.5 | 表现层：SSE | `presentation/api/v1/endpoints/agent_sse.py` | 设 `request.state.is_stream=True` 跳过统一包装 |
| 6.6 | 表现层：WebSocket | `presentation/api/v1/endpoints/agent_ws.py` | token 走 query 鉴权；每操作独立会话 |
| 6.7 | 迁移 | `migrations/versions/xxxx_agent.py` | 建出 conversations/messages |
| 6.8 | 测试 | `tests/integration/test_agent_api.py`（LLM 打桩） | 流式分片可拼回完整回复；历史可查 |

### P7 · 前端基座（M7）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 7.1 | 入口与全局样式 | `src/main.tsx`、`src/index.css`、`src/vite-env.d.ts` | `make dev-frontend` 可启动 |
| 7.2 | Query 客户端 | `src/lib/query-client.ts` | 提供 `queryClient` |
| 7.3 | API 客户端 | `src/lib/api.ts` | 解析统一信封；自动注入 Bearer token；错误统一提示 |
| 7.4 | 路由与布局 | `src/router.tsx`、`src/layouts/AppLayout.tsx` | 导航 + 嵌套路由 |
| 7.5 | 登录态 | `src/stores/auth.ts` | token 持久化（localStorage），未登录跳转登录页 |
| 7.6 | 登录/注册页 | `src/features/auth/*` | 登录成功后可进主页 |
| 7.7 | 测试 setup | `src/test/setup.ts` | `make test-frontend` 通过 |

### P8 · 前端业务页（M8）

| # | 任务 | 产出文件 | 验收标准 |
| --- | --- | --- | --- |
| 8.1 | 文章列表/详情 | `src/features/post/*`、`src/pages/*` | 列表分页、详情 Markdown 渲染 |
| 8.2 | 文章编辑器 | `src/features/post/editor/*` | 新建/编辑/发布/下架/删除 |
| 8.3 | 评论与点赞 | `src/features/comment/*`、`src/features/like/*` | 评论树展示、回复、点赞即时反馈 |
| 8.4 | Agent 聊天 | `src/features/agent/*` | 流式逐字显示，会话可切换 |
| 8.5 | 个人中心 | `src/features/profile/*` | 改资料/改密码 |
| 8.6 | 管理后台 | `src/features/admin/*` | 用户列表、角色分配（仅 admin 可见菜单） |
| 8.7 | 组件测试 | 对应 `*.test.tsx` | 关键交互测试通过 |

### P9 · 测试与质量（M9）

| # | 任务 | 产出 | 验收标准 |
| --- | --- | --- | --- |
| 9.1 | 后端单元测试 | `tests/unit/**` | domain 规则、值对象、权限矩阵全覆盖 |
| 9.2 | 后端集成测试 | `tests/integration/**` | 覆盖全部 API 主路径与错误分支 |
| 9.3 | 前端组件测试 | `src/**/*.test.tsx` | 关键页面可渲染、交互正确 |
| 9.4 | 覆盖率门槛 | `pyproject.toml` / vitest 配置 | 后端行覆盖 ≥ 80%；CI 达标才通过 |
| 9.5 | 静态检查 | `make lint` | ruff + eslint 零告警 |

### P10 · 部署与交付（M10）

| # | 任务 | 产出 | 验收标准 |
| --- | --- | --- | --- |
| 10.1 | 后端 Dockerfile | `apps/backend/Dockerfile`（多阶段） | 镜像可构建、可运行 |
| 10.2 | 前端 Dockerfile | `apps/frontend/Dockerfile` + Nginx | 静态产物可服务 |
| 10.3 | 全栈编排 | `docker-compose.prod.yml` | `docker compose up` 起 db+api+web |
| 10.4 | CI 流水线 | `.github/workflows/ci.yml` | lint→test→build 全绿 |
| 10.5 | 生产加固 | `core/config.py`、`main.py` | 生产关 `/docs`；JSON 日志；密钥走环境变量 |

---

## 八、验收标准（DoD）

一个功能视为「完成」需同时满足：

- [ ] 四层落位正确：domain 无框架依赖，仓储接口在 domain、实现在 infrastructure。
- [ ] 事务边界只在 `core/database.py` 的 `get_db`，仓储内不 `commit`。
- [ ] 所有对外错误经 `core/exceptions.py` 统一为 `{code,message,data}` 信封。
- [ ] 出参 Schema 不泄露敏感字段（如 `password_hash`）。
- [ ] 新模型已加入 `infrastructure/persistence/models/__init__.py`，迁移可自动生成。
- [ ] 有对应的单元/集成测试，`make lint && make test` 全绿。

---

## 九、推进方式建议

1. **按里程碑线性推进**（M0→M10），每个里程碑结束打一次 tag，便于回滚。
2. **每个上下文严格四层落地**，可对照 [backend.md](./backend.md) 第 3–6 章的范式。
3. **先写领域与用例测试，再写仓储与接口**：domain/application 用内存替身即可单测，不必依赖数据库。
4. **每阶段结束提交一次**，提交信息遵循 `<type>(<scope>): <subject>`（如 `feat(blog): 支持文章软删除`）。

---

*计划生成日期：2026-09-30*
