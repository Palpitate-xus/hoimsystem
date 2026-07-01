import secrets
import warnings

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # 数据库配置（优先使用 DATABASE_URL，否则使用分项配置）
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "hoimsystem"

    DATABASE_URL: str = ""

    # JWT 密钥（生产环境必须通过环境变量设置！）
    SECRET_KEY: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:8091,http://127.0.0.1:8091,http://localhost:8080,http://127.0.0.1:8080"

    class Config:
        env_file = ".env"

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

        # 如果 SECRET_KEY 为空，生成一个随机密钥（仅用于开发）
        if not self.SECRET_KEY:
            self.SECRET_KEY = secrets.token_urlsafe(32)
            warnings.warn(
                "SECRET_KEY 未设置，已自动生成临时密钥。生产环境请务必通过环境变量设置强密钥！",
                RuntimeWarning,
                stacklevel=2,
            )


settings = Settings()
