from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///") or database_url == "sqlite:///:memory:":
        return None
    return Path(database_url.removeprefix("sqlite:///"))


@lru_cache
def _engine_for_url(database_url: str) -> Engine:
    sqlite_path = _sqlite_path_from_url(database_url)
    if sqlite_path:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_engine(database_url: str | None = None) -> Engine:
    return _engine_for_url(database_url or get_settings().sqlalchemy_database_url)


@lru_cache
def _session_factory_for_url(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return _session_factory_for_url(database_url or get_settings().sqlalchemy_database_url)


def get_db_session() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
