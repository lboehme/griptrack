"""On-device launch/bootstrap helper (#96).

backend.launcher is the in-process analog of docker-entrypoint.sh for the
eventual Android/Chaquopy build (#93): given an app-private directory, set
the DB path, migrate to head, provision a persistent session secret, and
serve the app on a fixed loopback host:port. These tests pin the
logic-bearing pieces as plain functions and exercise the assembled app at
the HTTP seam / over a real socket, on desktop — no Android seam involved.
"""

import importlib
import inspect
import os
import socket
import sys
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from backend.launcher import (
    DB_FILENAME,
    SESSION_SECRET_FILENAME,
    _uvicorn_config,
    bootstrap,
    build_app,
    database_url_for,
    ensure_session_secret,
    run_migrations,
    serve,
)
from backend.models import STARTER_GRIP_TYPES, GripType, TrainingProtocol, User

ENV_KEYS = (
    "GRIPTRACK_DATABASE_URL",
    "GRIPTRACK_SESSION_SECRET",
    "GRIPTRACK_ENV",
    "GRIPTRACK_BOOTSTRAP_TOKEN",
    "GRIPTRACK_WEBVIEW_BUILD",
)


@pytest.fixture(autouse=True)
def _isolate_launcher_env():
    """bootstrap()/run_migrations() mutate os.environ and (via
    backend.db) a process-wide engine on purpose — that's exactly what the
    real on-device launch wants (a single long-lived process). Restore
    both after each test so this file doesn't bleed state into the rest
    of the suite, same pattern tests/test_db_pragmas.py uses.
    """
    saved = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if "backend.db" in sys.modules:
            importlib.reload(sys.modules["backend.db"])


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- database_url_for --------------------------------------------------


def test_database_url_for_is_an_absolute_four_slash_sqlite_url(tmp_path):
    url = database_url_for(tmp_path)

    assert url == f"sqlite:///{(tmp_path / DB_FILENAME).resolve()}"
    assert url.startswith("sqlite:////")  # 3 literal + the path's leading "/"
    assert url.count("/", len("sqlite:")) >= 4


def test_database_url_for_accepts_string_path(tmp_path):
    url = database_url_for(str(tmp_path))

    assert url == f"sqlite:///{(tmp_path / DB_FILENAME).resolve()}"


# --- ensure_session_secret ----------------------------------------------


def test_ensure_session_secret_persists_and_reuses_across_calls(tmp_path):
    first = ensure_session_secret(tmp_path)
    second = ensure_session_secret(tmp_path)

    assert first == second
    assert len(first) > 20
    assert (tmp_path / SESSION_SECRET_FILENAME).read_text().strip() == first


def test_ensure_session_secret_accepts_string_path(tmp_path):
    first = ensure_session_secret(str(tmp_path))
    assert (tmp_path / SESSION_SECRET_FILENAME).read_text().strip() == first


def test_ensure_session_secret_differs_per_app_dir(tmp_path):
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"

    assert ensure_session_secret(dir_a) != ensure_session_secret(dir_b)


# --- run_migrations -------------------------------------------------------


def test_run_migrations_creates_schema_and_seeds_on_a_fresh_db(tmp_path):
    database_url = database_url_for(tmp_path)

    run_migrations(database_url)

    engine = create_engine(database_url)
    with Session(engine) as session:
        names = {gt.name for gt in session.exec(select(GripType)).all()}
        assert names == set(STARTER_GRIP_TYPES)

        protocols = session.exec(
            select(TrainingProtocol).where(TrainingProtocol.user_id.is_(None))
        ).all()
        assert len(protocols) == 1
        assert protocols[0].ramp_percentages == "50,65,80,90"
        assert protocols[0].base_work_set_reps == 5


def test_run_migrations_is_idempotent_for_a_resumed_launch(tmp_path):
    database_url = database_url_for(tmp_path)

    run_migrations(database_url)
    run_migrations(database_url)  # a later app launch re-runs this; must no-op

    engine = create_engine(database_url)
    with Session(engine) as session:
        assert len(session.exec(select(GripType)).all()) == len(STARTER_GRIP_TYPES)


# --- bootstrap --------------------------------------------------------


def test_bootstrap_forces_non_production_and_no_bootstrap_token(tmp_path, monkeypatch):
    # Simulate an ambient environment that would otherwise gate registration
    # or force Secure cookies — bootstrap() must override both.
    monkeypatch.setenv("GRIPTRACK_ENV", "production")
    monkeypatch.setenv("GRIPTRACK_BOOTSTRAP_TOKEN", "some-invite-style-code")
    monkeypatch.setenv("GRIPTRACK_WEBVIEW_BUILD", "0")

    database_url = bootstrap(tmp_path)

    assert database_url == database_url_for(tmp_path)
    assert "GRIPTRACK_ENV" not in os.environ
    assert "GRIPTRACK_BOOTSTRAP_TOKEN" not in os.environ
    assert os.environ["GRIPTRACK_WEBVIEW_BUILD"] == "1"
    assert os.environ["GRIPTRACK_DATABASE_URL"] == database_url
    assert os.environ["GRIPTRACK_SESSION_SECRET"] == ensure_session_secret(tmp_path)


def test_bootstrap_reuses_the_persisted_secret_across_calls(tmp_path):
    bootstrap(tmp_path)
    first_secret = os.environ["GRIPTRACK_SESSION_SECRET"]

    bootstrap(tmp_path)  # simulates a later "restart" of the launcher
    second_secret = os.environ["GRIPTRACK_SESSION_SECRET"]

    assert first_secret == second_secret


def test_bootstrap_accepts_string_path(tmp_path):
    database_url = bootstrap(str(tmp_path))
    assert database_url == database_url_for(tmp_path)


# --- build_app (HTTP seam) -----------------------------------------------


def test_build_app_serves_in_webview_mode_without_sw_or_manifest(tmp_path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/login")

    assert response.status_code == 200
    assert '<script src="/static/register-sw.js"' not in response.text
    assert '<link rel="manifest"' not in response.text


def test_build_app_accepts_string_path(tmp_path):
    app = build_app(str(tmp_path))

    with TestClient(app) as client:
        response = client.get("/login")

    assert response.status_code == 200


def test_build_app_registers_the_first_user_with_no_bootstrap_token(tmp_path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/register",
            data={"email": "owner@example.com", "password": "device-owner-pw"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    # Non-production mode (GRIPTRACK_ENV unset): no Secure cookie attribute,
    # or a plain-http WebView would silently refuse to store the cookie.
    assert "secure" not in set_cookie.lower()


def test_build_app_persists_to_the_app_dir_database(tmp_path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "owner@example.com", "password": "device-owner-pw"},
        )

    engine = create_engine(database_url_for(tmp_path))
    with Session(engine) as session:
        users = session.exec(select(User)).all()
    assert [user.email for user in users] == ["owner@example.com"]
    assert users[0].is_admin  # first registration on an empty DB becomes admin


# --- serve() wiring: plain asyncio/h11 runner, real socket ---------------


def test_uvicorn_config_uses_the_plain_asyncio_h11_runner(tmp_path):
    app = build_app(tmp_path)

    config = _uvicorn_config(app, "127.0.0.1", 0)

    assert config.loop == "asyncio"
    assert config.http == "h11"


def test_serve_wiring_boots_a_reachable_loopback_server(tmp_path):
    """Drives the exact config serve() would use, over a real TCP socket
    (mirrors tests/e2e/conftest.py's live_server pattern) — proves the
    bootstrapped app is actually servable, not just buildable."""
    app = build_app(tmp_path)
    port = _free_port()
    server = uvicorn.Server(_uvicorn_config(app, "127.0.0.1", port))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 10
        healthy = False
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/health", timeout=0.5).status_code == 200:
                    healthy = True
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        assert healthy, "server did not become healthy in time"

        response = httpx.post(
            f"{base_url}/register",
            data={"email": "owner@example.com", "password": "device-owner-pw"},
            follow_redirects=False,
        )
        assert response.status_code == 303
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_serve_signature_accepts_positional_host_and_port():
    params = list(inspect.signature(serve).parameters.values())
    assert len(params) >= 3
    assert params[0].name == "app_dir"
    assert params[1].name == "host"
    assert params[2].name == "port"
    # host and port must be POSITIONAL_OR_KEYWORD so Java/Kotlin bridges (like Chaquopy)
    # can call serve(app_dir, host, port) positionally.
    assert params[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[2].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
