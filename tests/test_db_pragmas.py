# Engine-level test (not the HTTP seam): asserts the WAL + busy_timeout
# pragmas backend.db.configure_sqlite_pragmas installs are actually active
# on a real file-backed connection. A file is required here — SQLite
# silently ignores WAL on ":memory:" databases (journal_mode stays
# "memory"), so an in-memory engine can't prove this works.
from sqlmodel import create_engine

from backend.db import SQLITE_BUSY_TIMEOUT_MS, configure_sqlite_pragmas


def test_sqlite_connections_enable_wal_and_busy_timeout(tmp_path):
    db_path = tmp_path / "pragma_check.db"
    engine = configure_sqlite_pragmas(
        create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    )

    with engine.connect() as conn:
        journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy_timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert journal_mode == "wal"
    assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS


def test_production_engine_has_the_pragmas_wired(tmp_path, monkeypatch):
    # Reload backend.db with GRIPTRACK_DATABASE_URL pointed at a temp file
    # to prove the module-level `engine` (what get_session actually uses)
    # carries the same pragmas, not just the helper in isolation.
    import importlib

    import backend.db as db_module

    db_path = tmp_path / "prod_pragma_check.db"
    monkeypatch.setenv("GRIPTRACK_DATABASE_URL", f"sqlite:///{db_path}")
    try:
        importlib.reload(db_module)
        with db_module.engine.connect() as conn:
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            busy_timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()

        assert journal_mode == "wal"
        assert busy_timeout == db_module.SQLITE_BUSY_TIMEOUT_MS
    finally:
        # Restore the module to its normal (env-default) state for any
        # later test in the same process.
        monkeypatch.delenv("GRIPTRACK_DATABASE_URL", raising=False)
        importlib.reload(db_module)
