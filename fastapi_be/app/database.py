from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


def build_engine_options(database_url: str) -> dict:
    options = {
        "pool_pre_ping": True,
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
    }
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update({
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
        })
        if database_url.startswith("postgresql"):
            options["connect_args"] = {
                "application_name": "hoimsystem-api",
                "options": f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}",
            }
    return options

engine = create_engine(
    settings.DATABASE_URL,
    **build_engine_options(settings.DATABASE_URL),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
