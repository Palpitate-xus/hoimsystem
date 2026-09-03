"""Safe database migration entry point used by deployment automation."""

import os
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.config import settings
from app.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def migrate(database_url: str | None = None) -> str:
    """Create a fresh schema or upgrade a versioned database.

    The historical initial Alembic revision was empty because old deployments
    relied on ``metadata.create_all``. Fresh installations are therefore built
    from current metadata *inside this dedicated migration process* and stamped
    at the current head. Existing databases must have an Alembic version so an
    unknown legacy schema is never silently stamped as current.
    """

    url = database_url or settings.DATABASE_URL
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        application_tables = tables - {"alembic_version"}
        alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
        alembic_config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

        if not application_tables:
            Base.metadata.create_all(bind=engine)
            command.stamp(alembic_config, "head")
            return "bootstrapped"

        if "alembic_version" not in tables:
            if os.getenv("MIGRATION_ADOPT_EXISTING", "").lower() not in {"1", "true", "yes"}:
                raise RuntimeError(
                    "检测到未纳入 Alembic 管理的既有数据库；请先备份并完成结构核对，"
                    "确认兼容后设置 MIGRATION_ADOPT_EXISTING=true 进行一次性接管"
                )
            Base.metadata.create_all(bind=engine)
            command.stamp(alembic_config, "head")
            return "adopted"

        command.upgrade(alembic_config, "head")
        return "upgraded"
    finally:
        engine.dispose()


def main() -> None:
    print(f"database migration: {migrate()}")


if __name__ == "__main__":
    main()
