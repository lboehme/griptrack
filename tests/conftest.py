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
            seed_session.add(GripType(name=name))
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
