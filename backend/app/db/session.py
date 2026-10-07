"""Async engine and session factory."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _set_sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    # SQLite does not enforce foreign keys unless asked to, per connection.
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL lets the history view read while a recommendation is being written.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url)
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
