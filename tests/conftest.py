import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.db import configure_sqlite_pragmas, get_session
from backend.main import create_app
from backend.models import STARTER_GRIP_TYPES, GripType, TrainingProtocol


def build_client() -> TestClient:
    """A TestClient wired to a fresh, isolated in-memory SQLite DB.

    Every call gets its own engine, so no state leaks between tests.
    All tests drive the app through this HTTP seam only.
    """
    engine = configure_sqlite_pragmas(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as seed_session:
        # Mirrors the data migrations that seed production: starter grip
        # types and the single global TrainingProtocol row (ADR-0005).
        for name in STARTER_GRIP_TYPES:
            dimension = "block width" if name == "pinch" else "edge depth"
            seed_session.add(GripType(name=name, dimension_name=dimension))
        seed_session.add(TrainingProtocol(user_id=None))
        seed_session.commit()

    app = create_app()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


@pytest.fixture
def client():
    with build_client() as test_client:
        yield test_client


@pytest.fixture
def client_factory():
    """For tests that must set env vars before the app is constructed."""
    return build_client


# A fixed, known device token for webview_client (ADR-0013, #145) -- tests
# assert against this value directly rather than reading a real token file,
# since backend.auth.device_login reads GRIPTRACK_DEVICE_TOKEN live from the
# environment (same pattern GRIPTRACK_BOOTSTRAP_TOKEN already uses).
WEBVIEW_DEVICE_TOKEN = "test-device-token-0123456789"


@pytest.fixture
def webview_client(monkeypatch, client_factory):
    """A TestClient for the WebView build (ADR-0013): GRIPTRACK_WEBVIEW_BUILD
    and a known GRIPTRACK_DEVICE_TOKEN are set before create_app() runs, so
    /device-login and /welcome are registered and device sign-in is
    exercisable against WEBVIEW_DEVICE_TOKEN."""
    monkeypatch.setenv("GRIPTRACK_WEBVIEW_BUILD", "1")
    monkeypatch.setenv("GRIPTRACK_DEVICE_TOKEN", WEBVIEW_DEVICE_TOKEN)
    with client_factory() as test_client:
        yield test_client


@pytest.fixture
def session_date_is_today(monkeypatch):
    """Pins the server's "today" to 2026-07-04, the fixed session date most
    HTTP-seam tests log against, for tests about live-session behaviour
    (the rest step) rather than retro-logging: a set committed on a past
    date never starts a rest (PR #154 review)."""
    from datetime import date

    from backend import training_log

    monkeypatch.setattr(training_log, "server_today", lambda: date(2026, 7, 4))
