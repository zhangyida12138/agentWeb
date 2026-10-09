# AgentWeb 后端 DDD 分层实战手册

> 本文由《Python 框架实战教程》（duyi-service）的全部内容，按 **DDD（领域驱动设计）分层** 重新组织、重构而成。
> 目标是：**把教程里散落在「26 课 + 三层架构」中的知识与代码，归位到 DDD 的每一层，形成一份既可系统学习、又可直接对照落地的后端手册。**

---

## 目录

- [第 0 章 阅读指南](#第-0-章-阅读指南)
- [第 1 章 全局观：DDD 分层架构](#第-1-章-全局观ddd-分层架构)
- [第 2 章 core 内核：横切基础设施](#第-2-章-core-内核横切基础设施)
- [第 3 章 domain 领域层：业务不变量](#第-3-章-domain-领域层业务不变量)
- [第 4 章 application 应用层：用例编排](#第-4-章-application-应用层用例编排)
- [第 5 章 infrastructure 基础设施层：技术实现](#第-5-章-infrastructure-基础设施层技术实现)
- [第 6 章 presentation 表现层：接口与协议](#第-6-章-presentation-表现层接口与协议)
- [第 7 章 测试体系](#第-7-章-测试体系)
- [第 8 章 部署与交付](#第-8-章-部署与交付)
- [第 9 章 关键设计速查表](#第-9-章-关键设计速查表)
- [第 10 章 实操：按 DDD 层新增一个限界上下文](#第-10-章-实操按-ddd-层新增一个限界上下文)
- [附录 A 教程 26 课 → 本文章节 对照表](#附录-a教程-26-课--本文章节-对照表)
- [附录 B 一次请求的完整穿层时序](#附录-b一次请求的完整穿层时序)

---

## 第 0 章 阅读指南

### 0.1 本文与教程的关系

| 维度 | 教程（duyi-service） | 本文（AgentWeb DDD 版） |
| --- | --- | --- |
| 组织方式 | 按学习顺序：26 课 | 按架构分层：domain / application / infrastructure / presentation |
| 分层模型 | 三层架构：api / service / model | DDD 四层 + core 横切 |
| 讲述逻辑 | 「先能跑，再讲为什么」 | 「先定层，再归位知识」 |

**本文不搬运课程顺序，而是把每一课的知识点重新「归位」到它真正所属的架构层。** 同一个概念在教程里可能讲得很散，在本文里会集中出现在它该在的层，并说明「为什么属于这一层」。

### 0.2 怎么用这份手册

1. **想建立全局认知** → 读 [第 1 章](#第-1-章-全局观ddd-分层架构)，先记住「四层 + core」的职责与依赖方向。
2. **想查某个功能在哪** → 用 [附录 A 对照表](#附录-a教程-26-课--本文章节-对照表)，按教程课号反查本文位置。
3. **想照着写项目** → 读 [第 10 章 实操清单](#第-10-章-实操按-ddd-层新增一个限界上下文)，按层一个文件一个文件地建。
4. **想理解「为什么这么设计」** → 每个代码块都附有 `# 注释`，[第 9 章](#第-9-章-关键设计速查表)汇总了全部设计决策。

### 0.3 术语统一

| 本文术语 | 含义 | 教程中的对应叫法 |
| --- | --- | --- |
| 领域层 `domain` | 业务规则、实体、值对象、领域异常、仓储接口 | 无（教程用 model 混合承载了部分职责） |
| 应用层 `application` | 用例编排、事务边界、DTO | `service` |
| 基础设施层 `infrastructure` | ORM 模型、仓储实现、外部服务适配 | `model`、`duyi_utils`（部分） |
| 表现层 `presentation` | 路由、请求/响应 Schema、依赖注入 | `api`、`schema` |
| 内核 `core` | 配置、数据库会话、日志、中间件、认证 | `core` |

---

## 第 1 章 全局观：DDD 分层架构

### 1.1 一句话理解每一层

- **domain（领域层）**：*业务是什么*。企业的规则、概念、不变量，**不依赖任何框架**。
- **application（应用层）**：*业务怎么做*。编排用例、划定事务、协调领域对象与基础设施，**不含业务规则本身**。
- **infrastructure（基础设施层）**：*业务靠什么实现*。数据库、缓存、消息、第三方 SDK 的具体技术落地。
- **presentation（表现层）**：*业务怎么对外暴露*。HTTP 路由、参数校验、响应格式、认证入口。
- **core（内核）**：与分层正交的**横切能力**——配置、日志、数据库会话、中间件、异常处理器、OpenAPI。

### 1.2 依赖方向（最重要的一条规则）

```
presentation  ──▶  application  ──▶  domain  ◀──  infrastructure
      │                  │                                  │
      └──────────────────┴──────────── core ───────────────┘
```

**规则：依赖只能由外向内。**

- `domain` 谁都不依赖（最内层，纯 Python）。
- `application` 依赖 `domain`（用实体/值对象），并「面向接口」使用仓储（接口在 domain，实现见 3.4）。
- `infrastructure` 依赖 `domain`（实现其接口），但不被 `domain` 依赖——这就是**依赖倒置**。
- `presentation` 依赖 `application`，把 HTTP 请求翻译成用例调用。
- `core` 被各层共享，但自身不反向依赖业务分层。

> 教程里 `service → model → core` 是一条直线依赖；DDD 把它「掰弯」为围绕 domain 的依赖倒置，好处是 **domain 可脱离数据库与框架独立测试**。

### 1.3 教程概念 → DDD 层 的对照表（核心速查）

| 教程位置 | 教程职责 | 在 DDD 中归属 |
| --- | --- | --- |
| `app/api/*.py` | 路由、参数、状态码 | **presentation** |
| `app/schema/*.py` | Pydantic 请求/响应模型 | 拆分为 **presentation schemas**（对外）+ **application dto**（对内） |
| `app/service/*.py` | 业务逻辑 | **application**（用例）+ **domain**（规则） |
| `app/model/*.py` | SQLAlchemy ORM 模型 | **infrastructure/persistence/models** |
| `app/exception/base.py` | 业务异常基类 | **domain 层异常基类**（3.3） |
| `app/exception/handler/*` | 全局异常处理器、错误码 | **core**（6.5） |
| `app/core/config.py` | 配置 | **core** |
| `app/core/database.py` | 引擎/会话 | **core** |
| `app/core/auth.py` | 认证依赖 | **presentation/dependencies**（6.6） |
| `app/core/middleware/*` | 中间件 | **core**（6.3、6.4） |
| `app/core/logger/*` | 日志 | **core**（2.3） |
| `app/core/openapi.py` | 文档增强 | **core**（2.5） |
| `packages/duyi-utils` | 通用工具 | **infrastructure/adapters** 或 `packages/backend/shared` |

### 1.4 目标目录结构

```
apps/backend/src/app/
├── main.py                      # 应用装配（工厂 + lifespan + 注册）
├── core/                        # 横切内核
│   ├── config.py                #   配置（pydantic-settings）
│   ├── database.py              #   引擎 / 会话 / get_db
│   ├── logging.py               #   loguru 日志
│   ├── middleware/              #   中间件洋葱
│   ├── exceptions.py            #   全局异常处理器 + 错误码
│   └── openapi.py               #   文档增强
├── domain/                      # 领域层（纯业务，不依赖框架）
│   └── user/
│       ├── entities.py          #   实体 / 聚合根
│       ├── value_objects.py     #   值对象
│       ├── repositories.py      #   仓储接口（端口）
│       └── exceptions.py        #   领域异常
├── application/                 # 应用层
│   └── user/
│       ├── use_cases.py         #   用例编排
│       └── dto.py               #   应用 DTO
├── infrastructure/              # 基础设施层
│   └── persistence/
│       ├── base.py              #   DeclarativeBase + Mixin
│       ├── models/              #   ORM 模型
│       ├── mappers/             #   实体 ↔ 模型 映射
│       └── repositories/        #   仓储实现
└── presentation/                # 表现层
    ├── dependencies.py          #   依赖注入
    └── api/v1/
        ├── router.py            #   路由聚合
        ├── endpoints/           #   接口实现
        └── schemas/             #   请求/响应模型
```

> 前文提到 AgentWeb 已是这套结构，本文正是把教程的全部内容「翻译」进它。

---

## 第 2 章 core 内核：横切基础设施

> **本层回答**：与业务无关、但所有业务都要用的能力——配置、数据库、日志、中间件、文档。

### 2.1 配置管理（教程第 02 课）

**问题**：环境变量散落各处、命名冲突、导入时才报错太晚。

**方案**：用 `pydantic-settings` 分组建类，每组一个 `env_prefix`，模块级实例化做单例。

```python
# core/config.py
from pydantic_settings import BaseSettings


class BaseSettingsWithEnv(BaseSettings):
    # extra="ignore"：.env 中存在未声明的键也不报错，便于多服务共用一份 .env
    model_config = {"env_file": ".env", "extra": "ignore"}


class CommonSettings(BaseSettingsWithEnv):
    environment: str = "development"


class WebSettings(BaseSettingsWithEnv):
    app_name: str = "Web Service API"   # 读 WEB_APP_NAME
    jwt_secret_key: str = ""
    model_config = {"env_prefix": "WEB_"}   # 字段自动映射为 WEB_*


class DBSettings(BaseSettingsWithEnv):
    host: str = ""
    port: str = ""
    name: str = ""
    user: str = ""
    password: str = ""
    model_config = {"env_prefix": "DB_"}     # 读 DB_HOST 等


# 模块级单例：导入即完成读取与校验，配置有误会「尽早」在导入阶段抛错
common_settings = CommonSettings()
web_settings = WebSettings()
db_settings = DBSettings()
```

**为什么这样写**
- `env_prefix` 让不同分组的同名字段（例如两个 `host`）互不冲突。
- 单例避免各处重复解析，进程内配置一致。
- 错误的 `.env` 在启动瞬间暴露，而不是等到某个请求触发。

### 2.2 数据库引擎与会话（教程第 03、05 课）

**问题**：连接池怎么配？每个请求的事务边界在哪？

**方案**：惰性单例引擎 + `async_sessionmaker` + `get_db` 生成器划定事务。

```python
# core/database.py
_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = f"postgresql+asyncpg://{db_settings.user}:{db_settings.password}@{db_settings.host}:{db_settings.port}/{db_settings.name}"
        # pool_size=10 常驻连接；max_overflow=20 高并发时临时扩容；
        # pool_pre_ping 取连接前探活，剔除被 DB 断开的失效连接
        _engine = create_async_engine(url, pool_size=10, max_overflow=20,
                                      pool_pre_ping=True, echo=False)
    return _engine


async def get_db() -> AsyncGenerator[AsyncSession]:
    # 每个请求一个 Session：异常回滚 / 正常提交 / 必定关闭，划清事务边界
    session = get_session_factory()()
    session.begin()
    try:
        yield session
    except:
        await session.rollback()
        raise
    else:
        await session.commit()
    finally:
        await session.close()   # 归还连接，防止连接池泄漏
```

**关键点**
- `expire_on_commit=False`：commit 后不再过期对象属性，避免异步下访问已关闭 session 的属性报错。
- `get_db` 是 FastAPI 依赖，事务边界就是请求边界（**短事务**原则，见 4.3）。

### 2.3 日志体系（教程第 18 课）

**问题**：默认 print/uvicorn 日志零散、无法串联同一请求、慢查询不可见。

**方案**：`loguru` + `ContextVar`(request_id) + 慢查询事件。

```python
# core/logger/log_record.py
# 请求上下文 id：由日志中间件写入，随异步调用链自动透传
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("_request_id", default="")


def setup_logging() -> None:
    logger.remove()                     # 移除默认 handler，避免与控制台重复
    if common_settings.environment == "production":
        logger.add(sys.stdout, level=log_settings.level, serialize=True)  # JSON，便于 ELK 解析
    else:
        logger.add(sys.stdout, level=log_settings.level, format=..., colorize=True)
        logger.add("tmp/errors.log", level="ERROR", rotation="10 MB", retention="7 days")


@dataclass
class LogRecord:
    message: str
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        self._start_time = time.perf_counter()   # 构造即开始计时

    def _emit(self, level: LogLevel, exc: Exception | None = None) -> None:
        data = asdict(self)
        message = data.pop("message")
        extra = {k: v for k, v in data.items() if v}          # 过滤空字段
        extra.setdefault("request_id", request_id_var.get() or "-")
        log = logger.bind(**extra)
        if exc:
            log = log.opt(exception=exc)                       # 附带异常堆栈
        getattr(log, level.lower())(message)
```

慢查询用 SQLAlchemy 事件统计（**属于基础设施层的观测能力**）：

```python
# core/database.py
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before(...): _query_start_times[id(context)] = time.perf_counter()

@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after(...):
    start = _query_start_times.pop(id(context), None)
    duration = (time.perf_counter() - start) * 1000
    if duration >= log_settings.slow_query_threshold:
        DBLog(message="慢查询", sql=statement, params=str(parameters), duration_ms=round(duration, 2)).warning()
    else:
        DBLog(message="SQL执行", ...).debug()
```

**设计要点**
- 用 `id(context)` 作键：成对的 before/after 事件共享同一 context，`pop` 取回后删除，避免字典无限增长。
- 级别过滤交给 `LOG_LEVEL`，代码侧统一输出全部 SQL。

### 2.4 应用装配与 lifespan（教程第 15 课）

**问题**：日志/中间件/异常/路由的注册顺序有讲究；启动时要初始化数据。

**方案**：`main.py` 作为唯一装配点。

```python
# main.py
# 关闭 uvicorn 自带日志必须放在导入 fastapi/uvicorn 之前
logging.getLogger("uvicorn.error").disabled = True
logging.getLogger("uvicorn.access").disabled = True

from fastapi import FastAPI

setup_logging()   # ① 先初始化日志


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时：用单个事务幂等初始化系统设置，保证请求进来时配置已就绪
    async with get_session_factory().begin() as session:
        await SettingService(session).initialize()
    yield


app = FastAPI(lifespan=lifespan, title=web_settings.app_name,
              docs_url=None if common_settings.environment == "production" else "/docs")

register_middleware(app)                                   # ② 中间件（先于路由）
setup_openapi(app)                                         # ③ 文档增强
app.add_exception_handler(RequestValidationError, exception_handler)  # ④ 异常处理器
app.add_exception_handler(HTTPException, exception_handler)
app.add_exception_handler(Exception, exception_handler)

from app.api.health import router as health_router         # ⑤ 最后注册路由
app.include_router(health_router)
# ...
```

**顺序为什么重要**
1. 日志最先 → 后续所有初始化都能记录。
2. 中间件先于路由 → 中间件作用于整个应用。
3. 路由最后导入 → 保证日志/中间件/异常/文档就绪后再加载接口模块。
4. `lifespan` 用 `yield` 切分启动/关闭逻辑。

### 2.5 OpenAPI 文档增强

统一响应信封（见 6.3）会让默认文档失真，因此用猴子补丁重写 `app.openapi`，把每个 2xx 响应包装成 `ApiResponse_<模型名>` 组件；再从 `ERROR_MAP` 自动生成错误码说明注入 `/docs`（见 6.5）。**同源生成，杜绝「文档一套、实现一套」。**

---

## 第 3 章 domain 领域层：业务不变量

> **本层回答**：这个业务的核心概念是什么？有什么不可违背的规则？
> **铁律**：不 import 任何 FastAPI / SQLAlchemy / Pydantic，纯 Python。

### 3.1 实体与聚合根

**实体**：有唯一标识、生命周期内标识不变的对象。
**聚合根**：一组实体的入口，外部只能通过它访问内部，保证一致性边界。

以教程「用户系统」（第 17 课）为例，`User` 在 DDD 中是**实体**，其领域规则是「密码必须以哈希形态存在、用户名唯一」：

```python
# domain/user/entities.py
from dataclasses import dataclass, field


@dataclass
class User:
    """用户实体（聚合根）。只表达业务概念，不关心如何持久化。"""
    username: str
    password_hash: str
    id: int | None = None
```

> 教程里 `User` 直接写在 `model/user.py`（SQLAlchemy 模型）里，**业务与持久化耦合**。DDD 把它一分为二：`domain` 的纯实体 + `infrastructure` 的 ORM 模型，用 mapper 翻译（见 5.3）。

### 3.2 值对象

**值对象**：无标识、靠值相等、**不可变**。教程里的 JWT 载荷、分页元信息都适合做值对象。

```python
# domain/user/value_objects.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Username:
    """用户名的值对象：构造即校验，保证领域内永远拿不到非法用户名。"""
    value: str

    def __post_init__(self) -> None:
        if not (1 <= len(self.value) <= 100):
            raise ValueError("用户名长度必须在 1~100 之间")
```

`frozen=True` 保证不可变——这正是教程 `SettingDef`/`SettingGroupDef` 用 `@dataclass(frozen=True)` 的同一思想（见 4.3）。

### 3.3 领域异常

**领域异常**表达的是「业务规则被违反」，与 HTTP 无关。

```python
# domain/exceptions.py
class DomainException(Exception):
    """领域异常基类：所有业务规则违反都从这里派生，上层可一击捕获。"""
    def __init__(self, message: str, *, detail: str = "", original_exception: Exception | None = None):
        self.message = message                              # 可对外展示
        self.detail = detail                                # 内部排查用
        self.original_exception = original_exception        # 保留原始异常对象，便于打印堆栈
        super().__init__(message)


# domain/user/exceptions.py
class UserAlreadyExists(DomainException):
    """用户名已存在"""

class InvalidCredentials(DomainException):
    """用户名或密码错误"""
```

> 这就是教程 `app/exception/base.py` 的 `BusinessException`，只是**归位到领域层**。`message` 位置传参、`detail`/`original_exception` 强制关键字，都是原教程的设计。

### 3.4 仓储接口（端口 · 依赖倒置的落点）

**仓储接口定义在 domain，实现放 infrastructure**，这样 application 只依赖抽象。

```python
# domain/user/repositories.py
from abc import ABC, abstractmethod
from .entities import User


class UserRepository(ABC):
    """用户仓储接口（端口）。只声明「需要什么能力」，不关心怎么实现。"""

    @abstractmethod
    async def find_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def find_by_id(self, user_id: int) -> User | None: ...

    @abstractmethod
    async def save(self, user: User) -> User: ...
```

**为什么值得多写一层接口**：教程里 `UserService` 直接 `select(User)`，写死在 SQLAlchemy 上；有了接口，单元测试可以塞一个内存实现（见 7.3 Stub），应用层完全不碰数据库。

### 3.5 ORM 模型到底属于哪一层？

**答：infrastructure。** 教程的 `model/` 层其实是「持久化模型」，属于技术实现细节，因此归位到 `infrastructure/persistence/models/`（见 5.1）。domain 只保留纯实体。

---

## 第 4 章 application 应用层：用例编排

> **本层回答**：一次业务操作要做哪几步？事务怎么划？对外/对内用什么数据结构？

### 4.1 用例（Use Case）

教程的 `Service` 在 DDD 中拆为：**用例（编排）** + **领域规则（下沉到 domain）**。用例只做「取数据 → 调规则 → 存数据」的编排。

```python
# application/user/use_cases.py
from domain.user.repositories import UserRepository
from domain.user.exceptions import UserAlreadyExists, InvalidCredentials
from .dto import RegisterCommand, TokenDTO


class RegisterUserUseCase:
    """注册用例：编排仓储与领域规则，本身不含密码规则等业务细节。"""
    def __init__(self, repo: UserRepository):
        # 依赖抽象而非具体实现（构造注入），便于替换与测试
        self.repo = repo

    async def execute(self, cmd: RegisterCommand) -> int:
        if await self.repo.find_by_username(cmd.username) is not None:
            raise UserAlreadyExists("注册失败：用户名已存在")
        user = User(username=cmd.username, password_hash=hash_password(cmd.password))
        saved = await self.repo.save(user)
        return saved.id
```

### 4.2 DTO：Command / Query / VO（教程第 13 课）

**问题**：教程 `schema/user.py` 一个文件里塞了请求模型和响应模型，职责混杂。

**方案**：DTO 按用途分三类，并**分层放置**：

| 类型 | 方向 | 放置位置 | 示例 |
| --- | --- | --- | --- |
| **Command** | 入（写） | `application/*/dto.py` | `RegisterCommand` |
| **Query** | 入（读） | `application/*/dto.py` | `ListUsersQuery` |
| **VO / DTO** | 出 | `application/*/dto.py` | `UserDTO`、`TokenDTO` |
| 请求/响应模型 | 对外 HTTP | `presentation/.../schemas/` | `UserRegister`、`UserResponse` |

```python
# application/user/dto.py
from dataclasses import dataclass


@dataclass
class RegisterCommand:
    """注册命令（应用层入参）：不含 pydantic 校验，校验在外层 schema 完成。"""
    username: str
    password: str


@dataclass
class UserDTO:
    """用户出参：只暴露 id/username，绝不包含 password_hash。"""
    id: int
    username: str
```

> 关键区别：**presentation 的 schema 负责「HTTP 校验 + 序列化」，application 的 dto 负责「层间传参」**。教程把两者都放 `schema/`，DDD 里拆开更清晰。

### 4.3 事务边界：短事务 vs 长事务（教程第 16 课）

**核心原则**
- **短事务**：能多快结束就多快结束，绝不把「慢操作（外部网络、流式输出）」夹在事务里。
- **长操作前先归还连接**：这是本教程最有价值的实践之一。

```python
# application/ai/use_cases.py（对应教程 AiService 第 16/19/20 课）
async def initialize(self, user_id: int, product_id: int):
    # 1) 例行查询都在事务内快速完成
    product = await self._load_product(product_id)
    config = await self._get_required_ai_config()

    # 2) 【关键】流式输出可能持续数秒，先把连接归还连接池，别一直占着
    await self.db.commit()
    await self.db.close()

    full_response = ""
    async for chunk in ai_chat.chat_stream([...]):   # 慢操作：不占数据库连接
        full_response += chunk
        yield chunk

    # 3) 慢操作结束，merge 重新挂载脱离的实体，再落库
    conv = await self.db.merge(conv)
    await self.db.flush()
```

**为什么 `merge`**：`db.close()` 后 `conv` 已 detached，直接 `flush` 不会生效，需 `merge` 重新挂到会话上。

**幂等同步（也属应用层编排）**：教程第 15 课的系统设置初始化，实质是「以代码清单为唯一事实来源，把数据库对齐过去」。

```python
# application/setting/use_cases.py
async def initialize(self) -> dict[str, int]:
    # 以 SETTINGS_DTO 为基准对齐数据库：缺失补建、存在刷新元信息、多余删除 → 可反复执行
    for group_def in SETTINGS_DTO:
        ...
        db_setting = Setting(...)   # 仅新建时写默认值；已存在项不覆盖 value，
    # 避免把运维在页面改过的配置冲掉
```

**幂等的三阶段**：① 补建/刷新分组 → ② 删除多余分组 → ③ 逐组同步配置项。**只新建时写默认值、已存在不覆盖 value**，是「代码声明」与「运行时数据」共存的关键。

### 4.4 应用异常 vs 领域异常

- **领域异常**（3.3）：业务规则被违反，来自 domain。
- **应用异常**：用例层面的问题，如「依赖的外部服务配置缺失」。

```python
# application/exceptions.py
from domain.exceptions import DomainException

class ApplicationException(DomainException):
    """应用层异常基类，仍继承领域异常，便于统一捕获。"""

class ExternalServiceNotConfigured(ApplicationException):
    """外部服务配置缺失（如 AI/OSS 配置未填写）"""
```

> 统一继承 `DomainException`，使全局处理器只需 `except DomainException` 即可兜住全部业务错误。

### 4.5 把用例接到表现层（教程第 08 课）

```python
# presentation/dependencies.py
async def get_user_repository(db: Annotated[AsyncSession, Depends(get_db)]) -> UserRepository:
    # 基础设施实现注入到应用层：表现层负责「组装」，应用层只认接口
    return SqlAlchemyUserRepository(db)


async def get_register_use_case(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> RegisterUserUseCase:
    return RegisterUserUseCase(repo)
```

**FastAPI 依赖注入要点（教程第 08 课）**
- `Depends` 声明依赖，`Annotated[X, Depends(...)]` 是推荐写法，类型信息不丢失。
- 依赖可嵌套成树；同一依赖在一次请求内默认缓存复用。
- `app.dependency_overrides[get_db] = ...` 可在测试中整体替换（见 7.2）。

---

## 第 5 章 infrastructure 基础设施层：技术实现

> **本层回答**：领域接口用什么技术落地？数据怎么存、怎么取、怎么映射？

### 5.1 ORM 模型与声明基类（教程第 04 课）

```python
# infrastructure/persistence/base.py
class Base(DeclarativeBase):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        # 类名小写即表名（User -> user），省去重复手写
        return cls.__name__.lower()


class IDMixin:
    # 自增主键统一策略：Identity() 交由数据库生成（Postgres 对应 IDENTITY）
    id: Mapped[int] = mapped_column(Identity(), primary_key=True)


class TimestampMixin:
    # 时间基准统一交给数据库：server_default 生成创建时间、onupdate 自动刷新更新时间
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

```python
# infrastructure/persistence/models/user.py
class User(Base, IDMixin, TimestampMixin):
    # username 唯一 + 索引：保证登录名唯一且按用户名查询走索引
    # 只存 password_hash，模型层永远不接触明文密码
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
```

**模型注册（易踩坑）**：必须在 `models/__init__.py` 中集中 import 全部模型，否则 SQLAlchemy / Alembic「看不见」其表，迁移会漏表。

```python
# infrastructure/persistence/models/__init__.py
from . import user  # noqa
from . import setting  # noqa
# ... 每个模型都要 import 一次
```

**关系与级联（教程第 04 课的设置模块）**

```python
class Setting(Base, IDMixin, TimestampMixin):
    key: Mapped[str] = mapped_column(String(200), unique=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("settinggroup.id", ondelete="CASCADE"))
    group: Mapped["SettingGroup"] = relationship(back_populates="settings")  # 多对一

class SettingGroup(Base, IDMixin, TimestampMixin):
    key: Mapped[str] = mapped_column(String(100), unique=True)
    settings: Mapped[list["Setting"]] = relationship(back_populates="group")  # 一对多
```

> 级联删除用数据库外键的 `ondelete="CASCADE"`，而非 ORM 层 `cascade`，语义更明确。

### 5.2 Alembic 迁移（教程第 06 课）

- 迁移脚本基于 `Base.metadata` 自动生成（`alembic revision --autogenerate`）。
- 因此「模型没被 import」=「迁移漏表」，与 5.1 的注册强相关。
- 测试环境用 Alembic `upgrade head` 建库（见 7.2）。

### 5.3 映射器 Mapper：实体 ↔ ORM 模型

DDD 里 domain 实体与 ORM 模型是两套对象，需要**显式翻译**，避免领域被持久化细节污染。

```python
# infrastructure/persistence/mappers/user.py
from domain.user.entities import User as UserEntity
from infrastructure.persistence.models.user import User as UserModel


def to_entity(model: UserModel) -> UserEntity:
    return UserEntity(id=model.id, username=model.username, password_hash=model.password_hash)


def to_model(entity: UserEntity) -> UserModel:
    return UserModel(username=entity.username, password_hash=entity.password_hash)
```

> 代价是多一层翻译；收益是 domain 可独立演进、可脱离数据库测试。**业务简单时可取舍**，但要注意保持「domain 无框架依赖」这条底线。

### 5.4 仓储实现（实现 domain 的端口）

```python
# infrastructure/persistence/repositories/user.py
class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(UserModel).where(UserModel.username == username))
        model = result.scalar_one_or_none()
        return to_entity(model) if model else None

    async def save(self, user: User) -> User:
        model = to_model(user)
        self.db.add(model)
        await self.db.flush()      # 拿到自增 id，但事务提交由外层 get_db 统一负责
        return to_entity(model)
```

**要点**
- **不在仓储里 commit**：事务边界归 `get_db`（2.2），仓储只做数据操作，保证一个请求一个事务。
- `flush` 只把 SQL 发到数据库并回填主键，不结束事务。
- 并发下的唯一约束冲突要归一为业务异常（见下方）。

```python
# 注册用例中的并发兜底（教程第 17 课）
try:
    self.db.add(user)
    await self.db.flush()
except IntegrityError as e:
    # 「先查重」只能给友好提示，并发下仍可能双写；唯一约束是最终防线
    raise UserAlreadyExists("注册失败：用户名已存在", detail=str(e), original_exception=e) from e
```

### 5.5 外部服务适配器（教程第 14、17、19 课）

**OSS 直传（第 14 课）**：应用服务器只签发凭证，文件由前端直传对象存储，不经过后端。

```python
# application/upload/use_cases.py
async def generate_upload_sign(self, filename: str, file_size: int) -> dict:
    # 后缀 → MIME → 是否图片，层层收敛，只放行图片
    suffix = get_suffix(filename)
    content_type = get_mime_type(suffix)
    if content_type not in IMAGE_MIME.values():
        raise UploadException(f"不支持的文件类型: {suffix}, 仅支持图片格式")

    oss = await self._get_oss_settings()   # 配置来自数据库 setting_group，非硬编码
    # 同步 OSS SDK 会阻塞事件循环，且不再需要数据库：先提交并归还连接
    await self.db.commit()
    await self.db.close()
    return AliyunOSSUploader(config).generate_upload_credentials(filename, file_size)
```

**JWT（第 17 课）**：签发与校验放在 shared 工具，`secret_key` 严格保密（对称签名，泄露即可伪造）。

```python
def create_token(data: dict, secret_key: str, *, expires_delta=None) -> str:
    payload = data.copy()
    if "sub" in payload and not isinstance(payload["sub"], str):
        payload["sub"] = str(payload["sub"])     # JWT 规范：sub 必须是字符串
    now = datetime.now(timezone.utc)
    payload.update({
        "jti": str(uuid.uuid4()),                # token 唯一标识，用于吊销/防重放
        "iat": now,
        "exp": now + (expires_delta or timedelta(hours=2)),
    })
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_token(token: str, secret_key: str) -> dict:
    # algorithms 显式限定 HS256，防 alg=none 算法混淆攻击；exp 过期自动抛错
    return jwt.decode(token, secret_key, algorithms=["HS256"])
```

**密码哈希（第 17 课）**：bcrypt 单向慢哈希 + 随机盐。

```python
def hash_password(password: str) -> str:
    # gensalt 随机盐写入结果串，相同密码也不同哈希 → 抗彩虹表
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    # checkpw 按哈希中的盐重算并用恒定时间比较，防时序攻击
    return bcrypt.checkpw(plain.encode(), hashed.encode())
```

**AI 对话（第 19 课）**：Jinja2 渲染系统提示词（模块级构建一次 Environment），密钥/模型从数据库配置读取。

```python
_template_dir = Path(__file__).parent / "template"
# Environment 较重且模板可复用：模块级只构建一次
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)))

def _render_system_prompt(self, product) -> str:
    template = _jinja_env.get_template("product_intro.j2")
    return template.render(product={...})   # 无关联字段统一传 None，模板里更好判断
```

---

## 第 6 章 presentation 表现层：接口与协议

> **本层回答**：外部怎么访问？参数怎么校验？成功/失败长什么样？谁有权限？

### 6.1 路由与 Schema（教程第 08、13 课）

```python
# presentation/api/v1/endpoints/auth.py
router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: UserRegister,
    use_case: Annotated[RegisterUserUseCase, Depends(get_register_use_case)],
):
    # 表现层只做：参数校验（schema）+ 转调用例；不含业务逻辑
    user_id = await use_case.execute(RegisterCommand(data.username, data.password))
    return UserResponse(id=user_id, username=data.username)
```

**Schema 设计要点（教程第 13 课）**
- 入参校验收敛在入口：注册 `password` 加 `min_length=6`，登录刻意不加约束（避免泄露规则、错误更统一）。
- 出参只暴露必要字段：`UserResponse` 只含 `id/username`，**从模型层杜绝密码泄露**。
- 状态码语义化：创建返回 `201`、无返回体返回 `204`。

```python
class UserRegister(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=100)

class UserResponse(BaseModel):
    id: int
    username: str
```

### 6.2 依赖注入入口

表现层是「组装工厂」：把基础设施实现注入应用层用例（见 4.5 与 6.6）。

### 6.3 统一响应信封（中间件 · 教程第 10 课）

**问题**：每个接口各写各的返回结构，前端难统一处理。

**方案**：中间件统一包装为 `{code, data, message}`。

```python
# core/middleware/response.py
_NO_BODY_STATUS = frozenset(range(100, 200)) | {204, 304}


async def unified_response(request: Request, call_next):
    response = await call_next(request)

    # 以下情况不包装：非 /api/ 路径、异常处理器已自组装信封、SSE 流式、HEAD、无响应体状态码
    if (not request.url.path.startswith("/api/")
            or getattr(request.state, "exception_handled", False)
            or getattr(request.state, "is_stream", False)
            or request.method == "HEAD"
            or response.status_code in _NO_BODY_STATUS):
        return response

    body = b""
    async for chunk in response.body_iterator:      # 按块产出，需拼回完整字节
        body += chunk

    headers = dict(response.headers)
    headers.pop("content-length", None)             # 重新序列化后长度变化，交由 JSONResponse 重算
    data = json.loads(body) if body else None

    return JSONResponse(
        content={"code": "0", "data": data, "message": "success"},  # 成功 code 固定 "0"
        status_code=response.status_code,           # 保留 201 等语义
        headers=headers,
    )
```

**注意**：`request.state.exception_handled` / `is_stream` 是「跳过包装」的协商标记，分别由异常处理器、SSE 接口设置。

### 6.4 中间件洋葱（教程第 10 课）

```python
# core/middleware/__init__.py
MIDDLEWARES = [
    process_time.MIDDLEWARE,   # 计时 → 写 X-Process-Time 头
    logging.MIDDLEWARE,        # 生成 request_id，请求结束记日志
    cors.MIDDLEWARE,           # CORS（类中间件）
    response.MIDDLEWARE,       # 统一响应信封（最内层，最后包装）
]


def register_middleware(app: FastAPI) -> None:
    for callable_obj, kwargs in MIDDLEWARES:
        # 自动区分类中间件与函数式中间件，新增中间件只需往列表加一项
        if inspect.isclass(callable_obj):
            app.add_middleware(callable_obj, **kwargs)
        else:
            app.middleware("http")(callable_obj, **kwargs)
```

**洋葱顺序**：列表越靠前越「外层」。请求自外向内穿，响应自内向外穿。

- `process_time` 用 `perf_counter`（单调时钟，不受系统时钟回拨影响），把耗时写进 `X-Process-Time`。
- `logging` 每请求生成 `request_id` 写入 `ContextVar`，并把 `RequestLog` 挂到 `request.state`，供下游（如异常处理器）复用同一对象补充信息。
- `cors` 复用 Starlette 内置 `CORSMiddleware`；`allow_credentials=True` 时浏览器禁用通配符来源，故 `allow_origins` 必须显式配置，`expose_headers` 用于开放自定义响应头给前端 JS。

### 6.5 统一异常处理与错误码（教程第 09 课）

**问题**：异常散落、错误码不统一、内部细节泄露。

**方案**：异常基类（3.3）+ 集中错误码表 + 全局处理器（MRO 匹配）。

```python
# core/exceptions.py
# 把「异常类型」映射为 (业务错误码, HTTP 状态码, 默认消息)，集中一处，新增只需登记一行
ERROR_MAP: dict[type, tuple[str, int, str]] = {
    RequestValidationError: ("422001", 422, "数据验证错误"),
    DatabaseException: ("422002", 422, "数据验证错误"),
    UploadException: ("422003", 422, "上传数据验证错误"),
    NotFoundException: ("404001", 404, "资源不存在"),
    AuthException: ("401001", 401, "认证失败"),
    Exception: ("500001", 500, "服务器内部错误"),   # 兜底，保证响应结构永不漏网
}

PROTOCOL_ERROR_MAP = {404: "路径不存在", 405: "请求方法不允许", 415: "不支持的媒体类型"}


def _lookup(exc: Exception) -> tuple[str, int, str]:
    # 沿 MRO 向上找：子类未登记会自动命中父类配置；有 Exception 兜底，必然命中
    for exc_type in type(exc).__mro__:
        if exc_type in ERROR_MAP:
            return ERROR_MAP[exc_type]
    return ERROR_MAP[Exception]


async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request.state.exception_handled = True      # 通知响应中间件：别再二次包装
    if isinstance(exc, HTTPException):          # starlette/FastAPI 的 HTTPException 都走这支
        code, http_status = str(exc.status_code), exc.status_code
        body_msg = PROTOCOL_ERROR_MAP.get(exc.status_code, exc.detail)
    else:
        code, http_status, default_msg = _lookup(exc)
        if isinstance(exc, RequestValidationError):
            body_msg = "\n".join(_format_validation_error(e) for e in exc.errors())  # 一次告知全部校验错误
        elif isinstance(exc, DomainException):
            body_msg = exc.message              # 业务异常优先用抛出时的自定义 message
        else:
            body_msg = default_msg              # 未预期异常只回默认消息，不泄露内部细节

    log = request.state.request_log
    if log:
        log.message = f"请求异常: {body_msg}"
        log.error(exc=exc) if http_status == 500 else log.warning()   # 500 打堆栈，4xx 仅 warning

    return JSONResponse(status_code=http_status,
                        content={"code": code, "message": body_msg, "data": None})
```

**错误码规范**：前 3 位对应 HTTP 状态类别（422/404/401/500），后 3 位是同类序号，一眼可判来源。

**文档同源**：`generate_error_docs()` 从 `ERROR_MAP` 生成 Markdown 表注入 `/docs`，改错误码时文档自动同步。

### 6.6 认证：get_current_user（教程第 17 课）

```python
# presentation/dependencies.py
security_scheme = HTTPBearer()          # 既作校验依赖，又让 /docs 显示鉴权入口


async def get_user_from_token(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_token(token, web_settings.jwt_secret_key)
    except jwt.InvalidTokenError as e:
        # 统一同一条错误信息，不泄露 token 失效的具体原因
        raise AuthException("token 无效：token无效或已过期") from e

    sub = payload.get("sub")
    if sub is None:
        raise AuthException("token 无效：token无效或已过期")

    # token 有效不代表用户仍存在（可能已删除），回库确认后再放行
    user = await db.scalar(select(User).where(User.id == int(sub)))
    if user is None:
        raise AuthException("token 无效：token无效或已过期")
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await get_user_from_token(credentials.credentials, db)
```

路由中直接 `user: Annotated[User, Depends(get_current_user)]`，认证失败自动中断，业务函数无需写鉴权代码。

**登录/改密的业务规则（教程第 17 课）**
- 用户不存在与密码错误**统一返回同一提示**，避免被枚举用户名。
- 改密前必须校验原密码，防止会话被盗用后直接改密。
- JWT 过期时间从数据库配置读取（可运维动态调整），缺失回退默认值。

### 6.7 流式响应：SSE 与 WebSocket（教程第 20 课）

**SSE（服务端单向推送）**

```python
# presentation/api/v1/endpoints/ai_sse.py
@router.get("/initialize/{product_id}")
async def initialize_conversation(request: Request, product_id: int,
                                  user: Annotated[User, Depends(get_current_user)],
                                  db: Annotated[AsyncSession, Depends(get_db)]):
    request.state.is_stream = True      # 【关键】通知响应中间件：别包 JSON，否则流被破坏

    async def event_stream():
        try:
            async for chunk in AiService(db).initialize(user.id, product_id):
                yield f"data: {chunk}\n\n"        # SSE 协议：data: 开头、空行结尾
        except DomainException as e:
            # 此时 200 与响应头已发出，无法改状态码，只能推 error 事件
            yield f"event: error\ndata: {e.message}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**WebSocket（双向长连接）**

```python
@router.websocket("/{product_id}")
async def ai_websocket(websocket: WebSocket, product_id: int, token: str = Query(...)):
    # 浏览器 WebSocket API 无法自定义请求头，token 只能走 URL 查询参数，手动认证
    await websocket.accept()
    db = get_session_factory()()         # 长连接不能用请求级 get_db，手动建临时会话
    try:
        user = await get_user_from_token(token, db)
    except AuthException:
        await db.close()
        await websocket.close(code=1008, reason="认证失败")   # 1008 Policy Violation
        return
    await db.close()                      # 鉴权完立即归还连接，别长占
    # ... 每个操作单独建会话，独立事务边界
```

**对比**

| | SSE | WebSocket |
| --- | --- | --- |
| 方向 | 服务端 → 客户端（单向） | 双向 |
| 鉴权 | 可用 `Authorization` 头（走依赖） | 需 URL 传 token（无法自定义头） |
| 中间件 | 需打 `is_stream` 跳过统一包装 | 不走 HTTP 中间件 |
| 适用 | AI 流式输出等 | 实时双向交互 |

### 6.8 系统设置接口（教程第 15 课）

`GET` 返回分组化配置（按 id 排序保证展示顺序稳定）；`PUT` 批量更新：先转 `key→value` 映射，用一次 `IN` 查询批量取出，避免 N 次查库。

---

## 第 7 章 测试体系

> 教程第 11、12 课。测试按「层」来组织：domain 单测无需数据库，application 用 Stub 隔离，presentation 用集成/e2e。

### 7.1 测试金字塔与目录

```
test/
├── unit/          # 单元测试：domain 规则、工具函数（快，无 IO）
├── integration/   # 集成测试：真实数据库 + HTTP 客户端
└── e2e/           # 端到端：走完整链路
```

- **单元**：只测纯逻辑（值对象校验、密码哈希），毫秒级。
- **集成**：起 App + 真库，验证层间协作。
- **e2e / 冒烟**：模拟真实用户流程。

### 7.2 集成测试 conftest（依赖覆盖）

```python
# test/integration/conftest.py（节选）
def pytest_sessionstart(session):
    # 会话级：重建测试库并执行 Alembic 迁移到 head
    cur.execute(f"DROP DATABASE IF EXISTS {db_settings.name}")
    cur.execute(f"CREATE DATABASE {db_settings.name}")
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
async def db_session():
    # 用例级：清空所有表（TRUNCATE ... RESTART IDENTITY CASCADE）保证隔离
    for table in reversed(Base.metadata.sorted_tables):
        await conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    ...


@pytest.fixture
async def async_client(db_session):
    async def override_get_db():
        yield db_session
    # 【关键】用依赖覆盖把真实 get_db 换成测试会话
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)          # 不启真实端口，直接调 ASGI 应用
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}
```

**要点**：`ASGITransport` 直接驱动 ASGI，无需起服务器；`dependency_overrides` 是 FastAPI 官方的测试注入点。

### 7.3 Stub vs Mock

| | Stub | Mock |
| --- | --- | --- |
| 作用 | 提供**预设数据**（如假仓储） | **断言**是否被调用、调用几次 |
| 适用 | 替换慢依赖（DB/网络） | 验证交互行为 |

配合 3.4 的仓储接口，application 用例单测可注入内存版 `InMemoryUserRepository`，完全不碰数据库。

### 7.4 覆盖率门槛

CI 中设置覆盖率下限（如 80%），低于阈值即失败，防止「假绿」。

---

## 第 8 章 部署与交付

> 教程第 21–25 课。

### 8.1 Docker 多阶段构建

- **构建阶段**：装依赖（`uv sync` / 只装生产依赖）。
- **运行阶段**：拷贝虚拟环境 + 应用代码，使用精简基础镜像。
- 好处：镜像小、构建缓存复用、构建工具不进入运行时。

### 8.2 K8s / Helm

- K8s：Deployment（无状态副本）+ Service + ConfigMap/Secret（配置与密钥）+ 探针（liveness/readiness）。
- Helm：把上述资源参数化打包，按环境（dev/staging/prod）用不同 values 部署。

### 8.3 CI/CD

典型流水线：**lint → 测试（含覆盖率）→ 构建镜像 → 推镜像 → 部署**。
本文档所在 monorepo 的 `make` 是统一入口，适合作为 CI 各阶段的调用点。

### 8.4 生产环境注意

- 关闭交互式文档：`docs_url=None/redoc_url=None/openapi_url=None`（见 2.4）。
- 日志输出 JSON（`serialize=True`），便于采集系统解析。
- 密钥一律走环境变量 / Secret，绝不硬编码进仓库。

---

## 第 9 章 关键设计速查表

> 「为什么这样写」的集中索引。建议交叉阅读对应章节。

| # | 决策 | 一句话理由 | 章节 |
| --- | --- | --- | --- |
| 1 | 配置分组 + `env_prefix` | 防字段重名、错误尽早暴露 | 2.1 |
| 2 | 引擎/会话惰性单例 | 全进程一个连接池，避免重复创建 | 2.2 |
| 3 | `get_db` 划事务边界 | 异常回滚/正常提交/必定关闭 | 2.2 |
| 4 | `request_id` 用 ContextVar | 异步调用链自动透传，日志可串联 | 2.3 |
| 5 | 慢查询用 before/after 事件 | 精确统计每条真实 SQL 耗时 | 2.3 |
| 6 | 注册顺序：日志→中间件→异常→路由 | 依赖就绪后再加载 | 2.4 |
| 7 | domain 不依赖框架 | 可独立测试与演进 | 3 |
| 8 | 仓储接口在 domain，实现在 infra | 依赖倒置，可替换可 Mock | 3.4 |
| 9 | 领域异常继承统一基类 | 上层一击捕获全部业务错误 | 3.3 |
| 10 | 应用异常仍继承领域异常 | 全局处理器只需一个 except | 4.4 |
| 11 | schema（对外）与 dto（对内）分离 | 校验/序列化 vs 层间传参，职责清晰 | 4.2 |
| 12 | 长操作前先归还连接 | 流式/慢 IO 不占用数据库连接 | 4.3 |
| 13 | 幂等同步：只新建写默认值 | 不覆盖运维运行时改过的配置 | 4.3 |
| 14 | 模型集中在 `models/__init__` import | 否则迁移漏表 | 5.1 |
| 15 | 时间戳 `server_default`/`onupdate` | 时间基准统一交给数据库 | 5.1 |
| 16 | 仓储内不 commit | 事务归 `get_db`，保持一请求一事务 | 5.4 |
| 17 | 唯一约束作并发兜底 | 先查重只给友好提示，约束才是防线 | 5.4 |
| 18 | 密码 bcrypt 慢哈希 | 不可逆 + 可调成本 + 随机盐 | 5.5 |
| 19 | `sub` 转字符串、限定 HS256 | 符合 JWT 规范 + 防算法混淆攻击 | 5.5 |
| 20 | 统一响应信封中间件 | 前端处理一致；异常/流式需跳过 | 6.3 |
| 21 | 中间件列表化 + 自动区分类型 | 新增中间件零改注册函数 | 6.4 |
| 22 | 错误码前 3 位对齐 HTTP 类别 | 一眼判来源、便于检索 | 6.5 |
| 23 | 异常处理器按 MRO 查找 | 子类自动继承父类错误码 | 6.5 |
| 24 | 500 打堆栈、4xx 仅 warning | 未预期错误才触发告警 | 6.5 |
| 25 | 登录失败统一提示 | 防用户名枚举 | 6.6 |
| 26 | SSE 打 `is_stream` 标记 | 防止流式响应被包装破坏 | 6.7 |
| 27 | WebSocket token 走 URL | 浏览器无法给 WS 自定义请求头 | 6.7 |
| 28 | 测试用 `dependency_overrides` | 官方注入点，替换真实依赖 | 7.2 |
| 29 | 生产关闭 /docs | 不对外暴露接口结构 | 8.4 |

---

## 第 10 章 实操：按 DDD 层新增一个限界上下文

> 以新增「商品 `product`」为例，**自上而下指定接口、自内向外实现**。每一步标注所属层与文件。

### 步骤清单

1. **domain/product/entities.py**（领域层）
   - 定义 `Product` 实体/聚合根、不变量。
2. **domain/product/value_objects.py**
   - 如 `Price`（金额 > 0）、`SkuCode`。
3. **domain/product/exceptions.py**
   - `ProductNotFound(DomainException)` 等。
4. **domain/product/repositories.py**
   - `ProductRepository` 抽象接口（`find_by_id` / `list` / `save`）。
5. **application/product/dto.py**（应用层）
   - `CreateProductCommand`、`ProductDTO`。
6. **application/product/use_cases.py**
   - `CreateProductUseCase`、`ListProductsUseCase`（构造注入 `ProductRepository`）。
7. **infrastructure/persistence/models/product.py**（基础设施层）
   - SQLAlchemy 模型，`class Product(Base, IDMixin, TimestampMixin)`。
8. **infrastructure/persistence/models/__init__.py**
   - 追加 `from . import product  # noqa`（**别忘，否则迁移漏表**）。
9. **infrastructure/persistence/mappers/product.py**
   - `to_entity` / `to_model`。
10. **infrastructure/persistence/repositories/product.py**
    - `SqlAlchemyProductRepository(ProductRepository)`。
11. **presentation/api/v1/schemas/product.py**（表现层）
    - `ProductCreate`（入参校验）、`ProductResponse`（只暴露必要字段）。
12. **presentation/api/v1/endpoints/products.py**
    - `router = APIRouter(prefix="/api/products", tags=["商品"])`，注入用例。
13. **presentation/api/v1/router.py**
    - 聚合注册新路由。
14. **迁移**
    - `alembic revision --autogenerate -m "add product"` → 检查脚本 → `upgrade head`。
15. **测试**
    - `test/unit`：领域规则；`test/integration`：走 `async_client` 的 CRUD。

### 检查清单（提交前自问）

- [ ] domain 里有没有偷偷 import 框架？
- [ ] 事务边界是否只在 `get_db`，仓储里没有 commit？
- [ ] 出参 schema 是否排除了敏感字段？
- [ ] 新模型是否加入了 `models/__init__.py`？
- [ ] 新增业务异常是否登记进 `ERROR_MAP`？
- [ ] 是否有对应的单元/集成测试？

---

## 附录 A：教程 26 课 → 本文章节 对照表

| 教程课号 | 主题 | 本文位置 |
| --- | --- | --- |
| 01 | ASGI/WSGI、FastAPI 最小应用、/docs | 1.1、2.4、2.5 |
| 02 | 包结构、pydantic-settings、uv workspace | 2.1、1.4 |
| 03 | SQLAlchemy Core/ORM、Engine、参数化 | 2.2 |
| 04 | ORM 映射、DeclarativeBase、关系、Mixin | 5.1 |
| 05 | Session、事务、CRUD | 2.2、5.4 |
| 06 | Alembic 迁移 | 5.2、5.1 |
| 07 | 业务逻辑、Service、异常 | 4.1、3.3 |
| 08 | 依赖注入 Depends/Annotated | 4.5、6.1 |
| 09 | 统一异常处理、错误码、MRO | 6.5、3.3 |
| 10 | 中间件、统一响应 | 6.3、6.4 |
| 11 | 测试框架 | 7.1 |
| 12 | 测试方案（单元/集成/e2e、Stub/Mock） | 7.1–7.4 |
| 13 | 三层架构、DTO/BO/VO | 0.3、4.2、6.1 |
| 14 | 文件上传（OSS 直传） | 5.5 |
| 15 | 系统设置（幂等同步、lifespan） | 2.4、4.3、6.8 |
| 16 | 长/短事务 | 4.3 |
| 17 | 用户系统（bcrypt/JWT/ContextVar） | 3.1、5.5、6.6 |
| 18 | 日志（loguru、request_id、慢查询） | 2.3 |
| 19 | AI 导购（Jinja2 提示词） | 5.5 |
| 20 | 流式响应（SSE/WebSocket） | 6.7 |
| 21 | Docker | 8.1 |
| 22 | 云资产 | 8.2 |
| 23 | K8s | 8.2 |
| 24 | CI/CD | 8.3 |
| 25 | 总结 | 第 9 章 |
| 26 | 收官检验 | 第 10 章检查清单 |

---

## 附录 B：一次请求的完整穿层时序

以 `GET /api/auth/me` 为例：

```
客户端
  │  HTTP GET /api/auth/me（带 Authorization: Bearer xxx）
  ▼
[core] process_time 中间件 ──────► 记开始时间
  ▼
[core] logging 中间件 ──────────► 生成 request_id，挂 RequestLog 到 request.state
  ▼
[core] cors 中间件 ─────────────► 处理跨域头
  ▼
[core] response 中间件 ─────────► 进入「待包装」状态
  ▼
[presentation] 路由匹配 /api/auth/me
  ├─ Depends(security_scheme) 解析 Bearer Token
  ├─ Depends(get_current_user) → 校验 JWT → 查库 → 注入 User（失败抛 AuthException）
  └─ Depends(get_db) 开启一个 Session/事务
  ▼
[application] ProfileUseCase.execute(user)
  ▼
[infrastructure] SqlAlchemyUserRepository.find_by_id() → select(User) → mapper.to_entity()
  ▼
[domain] User 实体 → 返回 UserDTO
  ▼
[presentation] UserResponse.model_validate(dto) → 返回给中间件栈
  ▲
[core] response 中间件 ◄───────── 包装为 {"code":"0","data":{...},"message":"success"}
  ▲
[core] logging 中间件 ◄────────── 未异常 → 记 success 日志（含耗时）
  ▲
[core] process_time ◄──────────── 写响应头 X-Process-Time
  ▲
客户端 ◄── 200 {"code":"0","data":{"id":1,"username":"..."},"message":"success"}
```

**失败路径**：若 `get_current_user` 抛 `AuthException` → 冒泡到 `[core] exception_handler`（Starlette 按 MRO 匹配）→ 打 `exception_handled` 标记 → 返回 `{"code":"401001","message":"...","data":null}` → 响应中间件检测到标记，跳过二次包装。

---

*本文由《Python 框架实战教程》的 26 课内容按 DDD 分层重构整理，愿它成为你落地后端时的案头手册。*
