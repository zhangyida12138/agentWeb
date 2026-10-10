from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    """应用元信息。"""

    name: str = "AgentWeb API"
    env: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    docs_enabled: bool = True
    port: int = 8000


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
        DB__URL           → db.url
        SECURITY__JWT_*   → security.jwt_*
        CORS__ALLOW_*     → cors.allow_*
        LLM__BASE_URL     → llm.base_url

    优先级（由高到低）：真实进程环境变量 → .env 文件 → 字段默认值。
    .env 的路径已锚定到 apps/backend/.env，与启动时的工作目录无关。
    """

    model_config = SettingsConfigDict(
        # ⚠️ pydantic-settings 的 env_file 用**相对路径**时是按「进程当前工作目录」解析的，
        # 不是按本文件所在目录。若从仓库根目录启动（cwd = agentWeb/），".env" 命中的是
        # 根目录那个**前端** .env——里面没有任何 APP__/DB__/SECURITY__ 配置，
        # 而 extra="ignore" 会把不认识的键静默丢弃，于是所有字段统统回落到默认值，
        # 不报任何错（表现为改 .env 不生效、连的库和 debug 开关都不对）。
        # 这里锚定到本文件位置：src/app/core/config.py → parents[3] == apps/backend
        # 注：文件不存在时 pydantic-settings 会静默跳过，因此容器里只注入环境变量的场景不受影响。
        env_file=Path(__file__).resolve().parents[3] / ".env",
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
                msg = "SECURITY__JWT_SECRET_KEY 必须在生产/预发环境显式配置，且长度不少于 32 字符"  # noqa: RUF001
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
