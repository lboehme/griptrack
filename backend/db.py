import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

# Support GRIPTRACK_DATABASE_URL (as documented) or fall back to DATABASE_URL / default sqlite file.
DATABASE_URL = os.environ.get("GRIPTRACK_DATABASE_URL") or os.environ.get("DATABASE_URL", "sqlite:///./griptrack.db")

# Automatically create the parent directory if it's a local SQLite file database and doesn't exist yet
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    # For sqlite:////absolute/path (starts with / after replacing sqlite:///)
    # and sqlite:///relative/path
    if db_path and db_path != ":memory:":
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

# How long (ms) a connection retries before raising "database is locked",
# once WAL still hits a writer collision.
SQLITE_BUSY_TIMEOUT_MS = 5000


def configure_sqlite_pragmas(engine: Engine) -> Engine:
    """Enable WAL mode + a busy_timeout on every connection this engine opens.

    Autosave means many small, concurrent writes; SQLite's default
    rollback-journal mode serializes writers and throws "database is
    locked" under exactly that workload. WAL lets readers run alongside a
    writer, and busy_timeout makes SQLite retry instead of failing
    immediately on the writer collisions that remain. Wired via a
    connect-time event (not connect_args) so it applies uniformly to the
    production engine below *and* any test engine — see
    tests/conftest.py, which calls this on its in-memory test engine too.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()

    return engine


engine = configure_sqlite_pragmas(
    create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
)


def get_session():
    with Session(engine) as session:
        yield session
