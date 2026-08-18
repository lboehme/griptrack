"""On-device launch/bootstrap helper (#96).

This is the in-process analog of `docker-entrypoint.sh` for the Android
build (#93/#97/#98): given an app-private directory, it sets the DB path,
runs Alembic migrations to head, provisions a persistent session secret,
and serves the *unchanged* `backend.main` app on a fixed loopback
host:port via the plain ASGI runner (#94's `--loop asyncio --http h11`
posture). Kept deliberately thin — no new Android seam here, just the
pure-Python entry point the Chaquopy shell will call at app start.

Deviation from the container entrypoint on purpose: no pre-migration
backup step. That safety net exists for a real deploy where a bad
migration could corrupt the one production volume; on a fresh on-device
DB there's nothing yet to protect, and `docker-entrypoint.sh` itself skips
the backup in exactly that case (empty/no current revision).
"""

from __future__ import annotations

import importlib
import os
import secrets
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config

if TYPE_CHECKING:
    from fastapi import FastAPI
    from uvicorn import Config as UvicornConfig

# The directory containing both the `backend` package and `migrations/`
# (this file lives at <project_root>/backend/launcher.py). Overridable per
# call for tests / alternate packaging layouts (e.g. Chaquopy's extracted
# asset directory), but defaults to "wherever this module actually is".
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_FILENAME = "griptrack.db"
SESSION_SECRET_FILENAME = "session_secret"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def database_url_for(app_dir: Path | str) -> str:
    """Absolute, four-slash `sqlite:////...` URL for the DB file in app_dir.

    The engine (backend.db) auto-creates the parent directory and applies
    WAL + busy_timeout per connection, so nothing else is needed here.
    """
    db_path = (Path(app_dir) / DB_FILENAME).resolve()
    return f"sqlite:///{db_path}"


def ensure_session_secret(app_dir: Path | str) -> str:
    """Return the device session secret, generating and persisting it once.

    Subsequent calls (i.e. subsequent app launches) reuse the same value
    read back from app_dir, so cookies signed on a prior run keep
    validating — never the dev fallback, never a fresh secret per launch.
    """
    app_path = Path(app_dir)
    app_path.mkdir(parents=True, exist_ok=True)
    secret_path = app_path / SESSION_SECRET_FILENAME
    if secret_path.exists():
        existing = secret_path.read_text().strip()
        if existing:
            return existing
    secret = secrets.token_urlsafe(32)
    secret_path.write_text(secret)
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass  # best-effort; irrelevant on Android's already-sandboxed app-private storage
    return secret


def _sync_backend_db_module() -> None:
    """Recompute backend.db's module-level DATABASE_URL/engine from the
    environment.

    backend.db reads GRIPTRACK_DATABASE_URL once, at import time, and
    migrations/env.py imports that constant to decide what to migrate. On
    the real on-device launch (a fresh process, this helper called first)
    backend.db simply hasn't been imported yet and picks up the env var
    on its own. In a long-lived process that already imported it (this
    module's own test suite, a REPL, a resumed launch) the constant would
    otherwise stay stale from whatever GRIPTRACK_DATABASE_URL was at
    first import, so reload it here — same pattern as
    tests/test_db_pragmas.py uses to prove the pragmas apply post-reload.
    """
    if "backend.db" in sys.modules:
        importlib.reload(sys.modules["backend.db"])


def run_migrations(database_url: str, *, project_root: Path = PROJECT_ROOT) -> None:
    """Run Alembic `upgrade head` programmatically against database_url.

    Builds the Alembic Config in code (no on-disk alembic.ini needed —
    keeps the Android asset package to backend/ + migrations/), points
    script_location at the packaged migrations/ tree, and puts
    project_root on sys.path so migrations/env.py's `import backend.models`
    resolves. On a fresh DB this creates the schema and applies every
    data-seed migration (starter grip_types, the global TrainingProtocol
    row).
    """
    os.environ["GRIPTRACK_DATABASE_URL"] = database_url
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    _sync_backend_db_module()

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", str(project_root / "migrations"))
    alembic_cfg.set_main_option("prepend_sys_path", root_str)
    alembic_cfg.set_main_option("path_separator", "os")
    command.upgrade(alembic_cfg, "head")


def bootstrap(app_dir: Path | str, *, project_root: Path = PROJECT_ROOT) -> str:
    """Run the full on-device bootstrap sequence against app_dir.

    Mirrors docker-entrypoint.sh: resolve + set the DB path, migrate to
    head, provision the persistent session secret. Also guarantees
    non-production cookie mode and no bootstrap-token gate, regardless of
    whatever the ambient environment happened to have set — the on-device
    launch is never a production deploy and never wants the invite-style
    bootstrap-token flow for a single-owner phone.

    Returns the database_url that was set, mostly for logging/tests.
    """
    app_path = Path(app_dir)
    app_path.mkdir(parents=True, exist_ok=True)

    database_url = database_url_for(app_path)
    run_migrations(database_url, project_root=project_root)

    secret = ensure_session_secret(app_path)
    os.environ["GRIPTRACK_SESSION_SECRET"] = secret

    os.environ.pop("GRIPTRACK_ENV", None)
    os.environ.pop("GRIPTRACK_BOOTSTRAP_TOKEN", None)
    os.environ["GRIPTRACK_WEBVIEW_BUILD"] = "1"

    return database_url


def build_app(app_dir: Path | str, *, project_root: Path = PROJECT_ROOT) -> FastAPI:
    """Bootstrap app_dir, then build and return the ready-to-serve FastAPI
    app. Split out from serve() so tests can drive it through TestClient
    (or a real socket) without this function itself binding one."""
    bootstrap(app_dir, project_root=project_root)

    # backend.main itself only reads env vars inside create_app() (at call
    # time), so no reload is needed for it — only backend.db (handled by
    # bootstrap -> run_migrations -> _sync_backend_db_module) needed one.
    from backend.main import create_app

    return create_app()


def _uvicorn_config(app: FastAPI, host: str, port: int) -> UvicornConfig:
    import uvicorn

    # loop="asyncio", http="h11": the same plain-runner posture #94 pins
    # explicitly in docker-entrypoint.sh, now that requirements.txt no
    # longer installs uvicorn[standard] (uvloop/httptools) — smallest
    # native-wheel surface for the eventual Chaquopy build.
    return uvicorn.Config(app, host=host, port=port, loop="asyncio", http="h11")


def serve(
    app_dir: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Bootstrap app_dir and serve it on host:port. Blocks until shut down.

    This is the single entry point the Android shell calls at app start.
    """
    import uvicorn

    app = build_app(app_dir, project_root=project_root)
    uvicorn.Server(_uvicorn_config(app, host, port)).run()
