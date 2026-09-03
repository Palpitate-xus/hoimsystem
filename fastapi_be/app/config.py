import secrets
import warnings

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ALLOWED_ORIGINS = "http://localhost:8091,http://127.0.0.1:8091,http://localhost:8080,http://127.0.0.1:8080"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"

    # 数据库配置（优先使用 DATABASE_URL，否则使用分项配置）
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "hoimsystem"
    DB_POOL_SIZE: int = Field(default=10, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=200)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=300)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60, le=86400)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=15000, ge=1000, le=300000)
    REDIS_URL: str = ""

    DATABASE_URL: str = ""

    # JWT 密钥（生产环境必须通过环境变量设置！）
    SECRET_KEY: str = ""
    ALLOWED_ORIGINS: str = DEFAULT_ALLOWED_ORIGINS
    LIS_INTEGRATION_KEY: str = ""
    PACS_INTEGRATION_KEY: str = ""
    MEDICAL_INSURANCE_INTEGRATION_KEY: str = ""
    PAYMENT_INTEGRATION_KEY: str = ""
    LIS_OUTBOUND_URL: str = ""
    PACS_OUTBOUND_URL: str = ""
    MEDICAL_INSURANCE_OUTBOUND_URL: str = ""
    PAYMENT_OUTBOUND_URL: str = ""
    INTEGRATION_HTTP_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)
    INTEGRATION_MAX_ATTEMPTS: int = Field(default=8, ge=1, le=30)
    INTEGRATION_OUTBOX_INTERVAL_SECONDS: int = Field(default=10, ge=1, le=300)
    AUTO_CREATE_SCHEMA: bool = True
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 3600

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"prod", "production"}

    @property
    def cors_origins(self) -> list[str]:
        values = [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]
        return values or ["http://localhost:8091"]

    def model_post_init(self, __context):
        # 如果没有设置 DATABASE_URL，则用分项配置拼接；开发环境无配置时回退到 SQLite
        if not self.DATABASE_URL:
            if self.DB_USER and self.DB_PASSWORD and self.DB_NAME:
                self.DATABASE_URL = f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            elif self.is_production:
                raise ValueError("生产环境必须设置 DATABASE_URL 或完整的数据库连接分项配置")
            else:
                self.DATABASE_URL = "sqlite:///./test.db"

        default_secret = self.SECRET_KEY == "change-me-in-production"
        if self.is_production and (not self.SECRET_KEY or default_secret):
            raise ValueError("生产环境必须通过 SECRET_KEY 设置强随机密钥，不能为空或使用默认值")

        if self.is_production:
            if self.AUTO_CREATE_SCHEMA:
                raise ValueError("生产环境必须设置 AUTO_CREATE_SCHEMA=false，并使用 Alembic 迁移数据库")
            configured_origins = [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]
            if not configured_origins or self.ALLOWED_ORIGINS.strip() == DEFAULT_ALLOWED_ORIGINS or "*" in configured_origins:
                raise ValueError("生产环境必须显式配置 ALLOWED_ORIGINS，且不能使用 * 或开发环境默认地址")
            outbound_urls = (
                self.LIS_OUTBOUND_URL,
                self.PACS_OUTBOUND_URL,
                self.MEDICAL_INSURANCE_OUTBOUND_URL,
                self.PAYMENT_OUTBOUND_URL,
            )
            if any(url and not url.lower().startswith("https://") for url in outbound_urls):
                raise ValueError("生产环境的外部系统回调地址必须使用 https://")

        # 如果 SECRET_KEY 为空，生成一个随机密钥（仅用于开发）
        if not self.SECRET_KEY:
            self.SECRET_KEY = secrets.token_urlsafe(32)
            warnings.warn(
                "SECRET_KEY 未设置，已自动生成临时密钥。生产环境请务必通过环境变量设置强密钥！",
                RuntimeWarning,
                stacklevel=2,
            )


settings = Settings()
