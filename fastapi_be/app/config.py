import secrets
import warnings
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库配置（优先使用 DATABASE_URL，否则使用分项配置）
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "hoimsystem"

    DATABASE_URL: str = ""

    # JWT 密钥（生产环境必须通过环境变量设置！）
    SECRET_KEY: str = ""

    class Config:
        env_file = ".env"

    def model_post_init(self, __context):
        # 如果没有设置 DATABASE_URL，则用分项配置拼接
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )

        # 如果 SECRET_KEY 为空，生成一个随机密钥（仅用于开发）
        if not self.SECRET_KEY:
            self.SECRET_KEY = secrets.token_urlsafe(32)
            warnings.warn(
                "SECRET_KEY 未设置，已自动生成临时密钥。"
                "生产环境请务必通过环境变量设置强密钥！",
                RuntimeWarning,
                stacklevel=2,
            )


settings = Settings()
