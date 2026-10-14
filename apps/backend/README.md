# AgentWeb Backend

FastAPI + DDD（领域驱动设计）+ SQLAlchemy 2.0（async）+ PostgreSQL + Alembic。

## 目录结构

```
src/app/
├── domain/          # 领域层：实体、值对象、仓储接口（无框架依赖）
│   └── user/
│       ├── entities.py        # 聚合根 User
│       ├── value_objects.py   # 值对象 Email
│       ├── repositories.py    # 仓储接口 UserRepository
│       └── exceptions.py      # 领域异常
├── application/     # 应用层：用例编排、DTO / Command / Query
│   └── user/
│       ├── use_cases.py       # UserUseCases
│       └── dto.py
├── infrastructure/  # 基础设施层：ORM 模型、仓储实现、映射
│   └── persistence/
│       ├── base.py            # DeclarativeBase
│       ├── models/            # SQLAlchemy 模型
│       ├── mappers/           # 实体 <-> 模型 转换
│       └── repositories/      # 仓储接口的 SQLAlchemy 实现
├── presentation/    # 表现层：路由、请求/响应模型、依赖注入
│   ├── dependencies.py
│   └── api/v1/{router.py,endpoints/,schemas/}
├── core/            # 配置、日志、数据库会话、异常处理
└── main.py          # create_app() 应用工厂
```

依赖方向严格单向：`presentation → application → domain`，`infrastructure → domain`。
领域层不导入 FastAPI、SQLAlchemy 或 Pydantic。

## 命令

```bash
make install          # uv sync
make dev              # http://localhost:8000/docs
make format           # ruff check --fix + ruff format
make lint             # ruff check + ruff format --check
make test             # 启动测试库 + pytest
make coverage         # 带覆盖率

make db-test-up       # 启动测试库容器（5433 / agent_web_test）
make db-test-down     # 停掉测试库容器

make migrate                       # alembic upgrade head
make revision m="add xxx table"    # 生成自动迁移
make downgrade                     # 回退一个版本
```

## 新增一个限界上下文（以 `order` 为例）

1. `domain/order/`：`entities.py`、`value_objects.py`、`repositories.py`、`exceptions.py`
2. `application/order/`：`dto.py`、`use_cases.py`（依赖 1 中的仓储接口）
3. `infrastructure/persistence/`：`models/order.py`、`mappers/order.py`、`repositories/order.py`
4. `presentation/dependencies.py` 注册依赖，`presentation/api/v1/` 增加 router
5. `make revision m="add orders"` 生成迁移

## 测试

### 三层测试

- `tests/unit/`：纯领域 / 应用层逻辑，用内存仓储，不连库、毫秒级。
  它不依赖 `prepared_test_database`，所以单跑 `uv run pytest tests/unit` 连 Docker 都不用起。
- `tests/integration/`：真实 PostgreSQL + `ASGITransport`，验证仓储、事务、约束、HTTP 契约。
- 集成测试不 mock 数据库：本项目最容易出事的地方（升到唯一索引、flush vs commit 的报错时机、
  递归查询）恰恰只有真库才暴露。

### 独立测试库（不会碰开发数据）

测试连的是 `docker-compose.yml` 里的 **`postgres-test`**：独立容器、独立数据卷，
端口 **5433**、库名 **agent_web_test**，与开发库（5432 / agent_web）物理隔离。

```bash
make db-test-up      # = docker compose up -d --wait postgres-test
uv run pytest        # 不需要再准备什么
```

`make test` 已经带上了 `db-test-up`；就算你直接 `uv run pytest`，也可以：

1. **会话开始**（`tests/conftest.py::prepared_test_database`，`db_engine` 的依赖）
   自动完成三件事：核对库名必须以 `_test` 结尾 → 等库可连 → `alembic upgrade head`。
   用 Alembic 而不是 `create_all`，所以「模型改了但没写迁移」在测试里就能看见。
2. 每个用例跑在一个**最终回滚的外层事务**里（`join_transaction_mode="create_savepoint"`），
   所以用例之间互不污染，也不需要清库或按顺序执行。

库名核对是一道防呆：连错库的症状不是报错，而是「测试全绿 + 开发数据被改掉」。
库没起来时也不需要猜：约 30 秒内会抛 `RuntimeError`，直接告诉你先跑 `make db-test-up`。

### 环境变量在 `.env.test`

> 所有测试相关的环境变量都在 **`apps/backend/.env.test`**（模板：`.env.test.example`），
> 不写在命令行里，也不写在 `conftest.py` 里。

- 加载规则：`APP__ENV=test` 时依次读 `.env` → `.env.test`，**后者覆盖前者**。
  所以 `.env.test` 只需写「测试与开发不同」的项，其余沿用 `.env` 或字段默认值。
- `pytest` 会在 `import app.*` 之前把 `APP__ENV` **钉死**成 `test`，
  因此不会出现「外部环境变量把测试带去开发库」的情况。
- `.env.test` 不含机密（它指向本机就够），可以提交进仓库；被忽略的是 `.env`。
