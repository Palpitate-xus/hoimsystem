"""Safe database migration entry point used by deployment automation."""

import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import MetaData, Table, create_engine, inspect, select

from alembic import command
from app.config import settings
from app.database_url import normalize_database_url
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

    url = normalize_database_url(database_url or settings.DATABASE_URL)
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

        # An empty marker table means Alembic would start from the historical
        # empty baseline. Validate exact recorded revisions before executing any
        # migration against an existing database, including symbolic aliases.
        version_table = Table("alembic_version", MetaData(), autoload_with=engine)
        if "version_num" not in version_table.c:
            raise RuntimeError("Alembic 版本表缺少 version_num，请先核对数据库来源")
        with engine.connect() as connection:
            versions = connection.execute(select(version_table.c.version_num)).scalars().all()
        scripts = ScriptDirectory.from_config(alembic_config)
        try:
            valid = bool(versions) and all(
                isinstance(version, str)
                and bool(version)
                and (revision := scripts.get_revision(version)) is not None
                and revision.revision == version
                for version in versions
            )
        except CommandError:
            valid = False
        if not valid:
            raise RuntimeError("Alembic 版本记录为空或无法识别，请先核对数据库来源与迁移文件")
        command.upgrade(alembic_config, "head")
        return "upgraded"
    finally:
        engine.dispose()


def main() -> None:
    print(f"database migration: {migrate()}")


if __name__ == "__main__":
    main()
