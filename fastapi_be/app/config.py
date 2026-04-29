from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://nonebot:Only.for.Nonebot@172.20.137.65:15432/hoimsystem_fastapi"
    SECRET_KEY: str = "django-insecure-zc+tdrflp4r^4oq)m-yodvi+wk3j6!c)dm%8pct(*g*evmowf+"

    class Config:
        env_file = ".env"


settings = Settings()
