"""Run Alembic migrations programmatically (at application startup)."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_path: Path) -> Config:
    # Built in code instead of reading alembic.ini, so it works from any working directory.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def upgrade_to_head(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(database_path), "head")


async def upgrade_to_head_async(database_path: Path) -> None:
    # Alembic is synchronous; keep it off the event loop.
    await asyncio.to_thread(upgrade_to_head, database_path)
