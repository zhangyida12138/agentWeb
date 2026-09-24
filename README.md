# agentWeb

Monorepo 项目：Python 后端（FastAPI + DDD + SQLAlchemy async + PostgreSQL）与 React 前端（Vite + TypeScript）。

## 技术栈

| 端 | 技术 |
| --- | --- |
| 后端 | Python 3.12 · uv · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL 16 · pytest |
| 前端 | Node 20 · pnpm · Vite · React · TypeScript · React Router · TanStack Query · UnoCSS · ESLint · Vitest |
| 工程化 | GNU Make（统一入口）· Prettier · ruff · husky + lint-staged（提交时自动格式化） |

## 环境要求

- **Python ≥ 3.12**，以及 [uv](https://docs.astral.sh/uv/)
- **Node ≥ 20.19**，以及 pnpm 10（`corepack enable pnpm` 即可获取匹配版本）
- **Docker** 与 Docker Compose（用于启动 PostgreSQL）
- **GNU Make**（Windows 可用 `choco install make`）

## 快速启动

### 1. 安装依赖

```bash
make install
```

等价于 `uv sync --directory apps/backend` + `pnpm install`。

### 2. 启动数据库

```bash
make db-up
```

会用 `postgres:16-alpine` 在 `localhost:5432` 启动容器，库名 `agent_web`，账号密码均为 `postgres`。

后端默认配置（`app/core/config.py`）与 `docker-compose.yml` 已对齐，**不创建 `.env` 也能直接跑**。如需自定义，复制 `apps/backend/.env.example` 为 `apps/backend/.env` 后修改。

### 3. 初始化数据库表

仓库中还没有迁移版本，首次运行先生成初始迁移：

```bash
cd apps/backend
make revision m="init users"
make migrate
cd ../..
```

### 4. 一键启动前后端

```bash
make dev
```

该命令用 `concurrently` 同时拉起两个服务，日志带 `[backend]` / `[frontend]` 前缀，**Ctrl+C 可一次性退出两个进程**。

| 服务 | 地址 |
| --- | --- |
| 前端页面 | http://localhost:5173 |
| 后端接口文档（Swagger） | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/api/v1/health |

前端已配置代理，页面里请求 `/api/**` 会自动转发到后端 `8000` 端口，无需处理跨域。

只想启动其中一端时，可用 `make dev-backend` 或 `make dev-frontend`。

## 常用命令

在仓库根目录执行：

| 命令 | 说明 |
| --- | --- |
| `make install` | 安装前后端依赖 |
| `make dev` | 并行启动前后端开发服务 |
| `make test` | 运行后端 pytest + 前端 vitest |
| `make build` | 打包后端（whl/sdist）+ 构建前端产物 |
| `make lint` | 代码检查（ruff + eslint） |
| `make format` | 代码自动格式化（ruff + prettier） |
| `make db-up` / `make db-down` | 启停 PostgreSQL 容器 |

数据库迁移在后端目录执行（`cd apps/backend`）：

```bash
make migrate                     # 升级到最新版本
make revision m="add xxx table"  # 依据模型变更生成迁移
make downgrade                   # 回退一个版本
```

## 目录结构

```
agentWeb/
├── apps/
│   ├── backend/          # FastAPI 后端，DDD 分层（详见 apps/backend/README.md）
│   └── frontend/         # React 前端
├── packages/
│   ├── backend/shared/   # Python 共享包 agent-web-shared（工具函数等）
│   └── frontend/shared/  # 前端共享包 @agent-web/shared（工具函数、hooks 等）
├── docker-compose.yml    # PostgreSQL 容器
├── Makefile              # 统一命令入口
└── .husky/pre-commit     # 提交前自动格式化改动文件
```

### 共享代码放哪里

- 前端公共代码（工具函数、hooks）放 `packages/frontend/<包名>/src/`，由 `pnpm-workspace.yaml` 的 `packages/frontend/*` 纳入工作区。新增包后运行 `pnpm install`，前端即可直接 `import { useDebouncedValue } from '@agent-web/shared'`（包内 `exports` 直接指向 TS 源码，无需构建）。
- 后端公共代码放 `packages/backend/<包名>/src/<模块名>/`。新增包后，在 `apps/backend/pyproject.toml` 的 `dependencies` 与 `[tool.uv.sources]` 中声明路径依赖，再 `uv sync --directory apps/backend`，之后即可 `from agent_web_shared import normalize_pagination`。
- `make lint` / `make format` 已覆盖 `packages/` 下的 TS 与 Python 代码；提交时的 husky 钩子同样会格式化这些文件。

## 提交前检查

已配置 husky + lint-staged：执行 `git commit` 时会自动对暂存区文件格式化——`.py` 走 `ruff check --fix` + `ruff format`，`.ts/.tsx/.json/.css` 等走 `prettier --write`。

前端测试文件放在 `apps/frontend/src/` 下，命名为 `*.test.ts(x)`，可用 `pnpm --filter frontend test:watch` 进入监听模式。
