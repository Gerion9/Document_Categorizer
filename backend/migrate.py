"""
Startup migration script.

- Fresh database  → create all tables via SQLAlchemy, then stamp Alembic to head
                    (skips migrations that assume tables already exist)
- Existing database → run pending Alembic migrations normally
"""
from alembic.config import Config
from alembic import command
from sqlalchemy import inspect

from app.core.config import get_runtime_settings
from app.database import engine, Base
from app import models  # noqa: F401 – registers all ORM models with Base


def resolve_migration_mode(existing_tables: set[str], *, allow_existing_schema_stamp: bool) -> str:
    if "alembic_version" in existing_tables:
        return "upgrade"

    non_alembic_tables = existing_tables - {"alembic_version"}
    if not non_alembic_tables:
        return "fresh"

    if allow_existing_schema_stamp:
        return "stamp_existing"

    return "abort_existing_without_alembic"


def main() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    alembic_cfg = Config("alembic.ini")
    settings = get_runtime_settings()
    migration_mode = resolve_migration_mode(
        existing_tables,
        allow_existing_schema_stamp=settings.ALLOW_ALEMBIC_STAMP_ON_EXISTING_SCHEMA,
    )

    if migration_mode == "fresh":
        print("Fresh database detected – creating all tables and stamping Alembic head.")
        Base.metadata.create_all(bind=engine)
        command.stamp(alembic_cfg, "head")
        return

    if migration_mode == "upgrade":
        print("Existing database detected – running pending Alembic migrations.")
        command.upgrade(alembic_cfg, "head")
        return

    if migration_mode == "stamp_existing":
        print("Existing schema without alembic_version detected – stamping Alembic head because ALLOW_ALEMBIC_STAMP_ON_EXISTING_SCHEMA=true.")
        command.stamp(alembic_cfg, "head")
        return

    raise RuntimeError(
        "Existing tables were found but alembic_version is missing. "
        "Refusing to stamp automatically. Inspect the schema first or set "
        "ALLOW_ALEMBIC_STAMP_ON_EXISTING_SCHEMA=true for a one-time controlled stamp."
    )


if __name__ == "__main__":
    main()
