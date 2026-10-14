import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ────────────────────────────── 该读哪些 env 文件 ──────────────────────────────
# 本文件位置：src/app/core/config.py → parents[3] == apps/backend
_BACKEND_DIR = Path(__file__).resolve().parents[3]
_BASE_ENV_FILE = _BACKEND_DIR / ".env"


def _resolve_env_name() -> str:
    """先定「现在是什么环境」，才能决定读哪些 env 文件。

    这里只能看 ``os.environ``：``Settings.app.env`` 正是由这些文件决定的，
    「读哪个文件」这件事本身就是鸡生蛋。代价是它必须在**首次导入本模块之前**
    设好（测试里由 ``tests/conftest.py`` 在 import app.* 之前钉成 test）。
    """

    return os.environ.get("APP__ENV", "development").strip().lower()


_ENV_NAME = _resolve_env_name()
# 叠加顺序：.env → .env.<env>，**靠后的覆盖靠前的**（pydantic-settings 按顺序 deep_update）。
# 有了这条规则，「公共配置」和「环境差异」就能分开放：开发库和测试库只差一行 DB__URL，
# 而不是把整份 .env 复制一遍再改三个地方——复制出来的副本迟早会和原版漂移。
# 文件不存在会被静默跳过（pydantic-settings 的行为），所以 CI 里没有 .env、
# 只有 .env.test 也能跑起来。
_ENV_FILES: tuple[Path, ...] = (_BASE_ENV_FILE, _BACKEND_DIR / f".env.{_ENV_NAME}")


class AppSettings(BaseModel):
    """应用元信息。"""

    name: str = "AgentWeb API"
    env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    docs_enabled: bool = True
    port: int = 8000
    # 首个管理员的引导邮箱（环境变量 APP__BOOTSTRAP_ADMIN_EMAIL）。
    #
    # 解决的是「鸡生蛋」：没有 admin 就没人能进管理接口，也就没人能把自己提成 admin。
    # 这里指定一个邮箱，用该邮箱注册时直接授予 admin 而不是默认的 reader。
    #
    # 只在「注册」这一个时刻生效——已存在的账号不会被事后提权。所以它是一次性引导手段，
    # 不是常驻的提权后门：上线后应当把这个值清空（或换成一个不会有人去注册的邮箱）。
    # 用 EmailStr 而不是 str：写错一个字母就静默不生效，是最难查的那类问题，
    # 宁可在启动时就因为格式非法直接报错。
    bootstrap_admin_email: EmailStr | None = None

    @field_validator("bootstrap_admin_email", mode="before")
    @classmethod
    def _blank_email_means_disabled(cls, value: object) -> object:
        """空串等价于「没配」。

        运维在 .env 里留一行 ``APP__BOOTSTRAP_ADMIN_EMAIL=``（值空着）来表示关闭，
        比删掉整行更常见、更不容易漏。不特判的话空串会进 EmailStr 校验，
        最后以一条「不是合法邮箱」的启动报错收场——排查方向会被彻底带偏。
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value


class DatabaseSettings(BaseModel):
    """数据库连接与连接池。"""

    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_web"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True


class SecuritySettings(BaseModel):
    """JWT 与密码哈希。

    注意：jwt_secret_key 允许 model 层面缺省（None），但在 Settings.model_post_init 中会
    根据 app.env 决定是否强制要求——development/test 允许缺省（自动生成临时值方便开发），
    staging/production 必须显式配置。
    """

    jwt_secret_key: SecretStr | None = Field(default=None, min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    bcrypt_rounds: int = Field(default=12, ge=4, le=20)


class CorsSettings(BaseModel):
    """跨域白名单。"""

    allow_origins: list[AnyHttpUrl | Literal["*"]] = ["http://localhost:5173"]
    allow_credentials: bool = True
    allow_methods: list[str] = ["*"]
    allow_headers: list[str] = ["*"]


class LLMSettings(BaseModel):
    """P6 Agent 用 LLM 客户端配置（现阶段可留空）。"""

    base_url: str | None = None
    api_key: SecretStr | None = None
    model: str | None = None


class Settings(BaseSettings):
    """全局配置聚合（pydantic-settings 自动从 .env + 环境变量读取）。

    字段匹配规则（ env_nested_delimiter="__" ）：
        APP__NAME         → app.name
        APP__BOOTSTRAP_ADMIN_EMAIL → app.bootstrap_admin_email
        DB__URL           → db.url
        SECURITY__JWT_*   → security.jwt_*
        CORS__ALLOW_*     → cors.allow_*
        LLM__BASE_URL     → llm.base_url

    优先级（由高到低）：真实进程环境变量 → .env.<env> → .env → 字段默认值。

    env 文件的路径已锚定到 apps/backend，与启动时的工作目录无关；
    ``<env>`` 取自 APP__ENV（默认 development），见文件顶部的 _ENV_FILES。
    """

    model_config = SettingsConfigDict(
        # ⚠️ pydantic-settings 的 env_file 用**相对路径**时是按「进程当前工作目录」解析的，
        # 不是按本文件所在目录。若从仓库根目录启动（cwd = agentWeb/），".env" 命中的是
        # 根目录那个**前端** .env——里面没有任何 APP__/DB__/SECURITY__ 配置，
        # 而 extra="ignore" 会把不认识的键静默丢弃，于是所有字段统统回落到默认值，
        # 不报任何错（表现为改 .env 不生效、连的库和 debug 开关都不对）。
        # 这里锚定到本文件位置：src/app/core/config.py → parents[3] == apps/backend
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="",  # 无前缀，直接用子模型名 __ 字段名
        extra="ignore",
        case_sensitive=False,
        frozen=True,
        validate_default=True,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    def model_post_init(self, __context) -> None:
        """在 pydantic 完成所有字段加载后做二次校验。"""

        if self.security.jwt_secret_key is None:
            if self.app.env in {"staging", "production"}:
                msg = "SECURITY__JWT_SECRET_KEY 必须在生产/预发环境显式配置，且长度不少于 32 字符"
                raise ValueError(msg)
            # development / test 环境允许缺省：自动生成一次性密钥（重启失效，仅用于开发调试）
            import secrets

            object.__setattr__(
                self,
                "security",
                SecuritySettings(
                    jwt_secret_key=SecretStr(secrets.token_urlsafe(48)),
                    jwt_algorithm=self.security.jwt_algorithm,
                    jwt_expire_minutes=self.security.jwt_expire_minutes,
                    bcrypt_rounds=self.security.bcrypt_rounds,
                ),
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """配置单例（避免每次读取都重解析 .env）。"""

    return Settings()
