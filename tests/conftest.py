import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.db import get_session
from backend.main import create_app


@pytest.fixture
def client():
    """A TestClient wired to a fresh, isolated in-memory SQLite DB.

    Every test gets its own engine, so no state leaks between tests.
    All tests drive the app through this HTTP seam only.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client
