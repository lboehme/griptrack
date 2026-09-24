"""Fixtures for the browser-smoke layer (tests/e2e/).

Unlike tests/conftest.py's build_client(), a Playwright browser is a
separate OS process — it can't drive FastAPI's in-process TestClient
transport. So this boots the real app under uvicorn, in a background
thread, listening on an ephemeral localhost port, with the same
isolated-DB-per-test + starter-data seeding approach as build_client().
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.db import configure_sqlite_pragmas, get_session
from backend.main import create_app
from backend.models import STARTER_GRIP_TYPES, GripType, TrainingProtocol

REGISTER_EMAIL = "e2e@example.com"
REGISTER_PASSWORD = "e2e-test-pw-1234"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server():
    """Boot the real app against a fresh isolated in-memory SQLite DB,
    seeded the same way build_client() is, on a real TCP port so a
    browser process can reach it. Yields the base URL; tears the server
    down afterwards."""
    engine = configure_sqlite_pragmas(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as seed_session:
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

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

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
    if not healthy:
        raise RuntimeError("live_server did not become healthy in time")

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)


def seed_max_tests(page, live_server, hands=("left", "right")):
    """Log a 40 kg max test for each hand on half crimp / 20 mm, so
    /session/play lands straight on the warmup rung step instead of the
    untested-hand estimate cards."""
    for hand in hands:
        page.goto(f"{live_server}/max-tests")
        form = page.locator('form[action="/max-tests"]')
        form.locator(f'input[name="hand"][value="{hand}"]').check()
        form.locator("select.grip-select").select_option(label=["Half crimp", "half crimp"])
        form.locator('input[name="edge_mm"]').fill("20")
        form.locator('input[name="weight"]').fill("40")
        form.locator('button[type="submit"]').click()


def start_session_play(page, live_server):
    """Seed both hands' max tests and start a session, landing on
    /session/play's first warmup rung step."""
    seed_max_tests(page, live_server)
    page.goto(f"{live_server}/session/new")
    page.locator(".grip-select").select_option(label=["Half crimp", "half crimp"])
    page.locator('input[name="edge_mm"]').fill("20")
    page.get_by_role("button", name="Start session").click()


def advance_to_worksets(page, max_rungs=8):
    """From a warmup rung step, click "Rung done" until the work-set step's
    hand cards appear (session play, #146: no more "Continue to work sets"
    link -- the ramp is entirely rung-by-rung)."""
    for _ in range(max_rungs):
        if page.locator(".hand-card").count() > 0:
            return
        page.get_by_role("button", name="Rung done").click()
        page.wait_for_timeout(200)
    assert page.locator(".hand-card").count() > 0, "Never reached the work-set step"


@pytest.fixture
def authenticated_page(live_server, page):
    """A Playwright `page` logged in as a freshly-registered user, sitting
    on the home page. Drives real form submits (not a cookie shortcut) so
    the smoke spec exercises the actual login-with-browser path."""
    page.goto(f"{live_server}/register")
    page.fill('input[name="email"]', REGISTER_EMAIL)
    page.fill('input[name="password"]', REGISTER_PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_server}/")
    return page
