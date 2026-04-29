from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_USER: str = "nonebot"
    DB_PASSWORD: str = "Only.for.Nonebot"
    DB_HOST: str = "172.20.137.65"
    DB_PORT: str = "15432"
    DB_NAME: str = "hoimsystem_fastapi"

    DATABASE_URL: str = ""
    SECRET_KEY: str = "django-insecure-zc+tdrflp4r^4oq)m-yodvi+wk3j6!c)dm%8pct(*g*evmowf+"

    class Config:
        env_file = ".env"

    def model_post_init(self, __context):
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )


settings = Settings()
