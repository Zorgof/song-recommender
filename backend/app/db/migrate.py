"""Run Alembic migrations programmatically (at application startup)."""

import asyncio
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.errors import ConfigurationError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_path: Path) -> Config:
    # Built in code instead of reading alembic.ini, so it works from any working directory.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def ensure_writable_dir(directory: Path) -> None:
    """Create the data directory; fail with a clear message if it cannot be written.

    SQLite would otherwise report only "unable to open database file". The usual cause is a
    bind-mounted directory owned by root, which Docker creates when the host path is missing.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(f"Cannot create the data directory {directory}: {exc}") from exc
    if not os.access(directory, os.W_OK | os.X_OK):
        raise ConfigurationError(
            f"The data directory {directory} is not writable by uid {os.getuid()}. "
            "In Docker, ./data on the host must be owned by that user, e.g. "
            "`sudo chown 1000:1000 data` in the repository root."
        )


def upgrade_to_head(database_path: Path) -> None:
    ensure_writable_dir(database_path.parent)
    command.upgrade(alembic_config(database_path), "head")


async def upgrade_to_head_async(database_path: Path) -> None:
    # Alembic is synchronous; keep it off the event loop.
    await asyncio.to_thread(upgrade_to_head, database_path)
