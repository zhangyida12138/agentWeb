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
make test             # pytest
make coverage         # 带覆盖率

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

- `tests/unit/`：纯领域/应用层测试，用 `tests/fakes.py` 的内存仓储，不需要数据库。
- `tests/integration/`：HTTP 接口测试，通过 `dependency_overrides` 替换仓储。

两层测试都不依赖真实的 PostgreSQL，可直接在 CI 中运行。
