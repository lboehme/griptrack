import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, text
from starlette.middleware.sessions import SessionMiddleware

from backend.db import get_session
from backend.routers import auth as auth_router
from backend.routers import home as home_router
from backend.routers import profile as profile_router
from backend.templating import templates

BACKEND_DIR = Path(__file__).parent

SESSION_SECRET = os.environ.get("GRIPTRACK_SESSION_SECRET", "dev-only-secret")


def create_app() -> FastAPI:
    app = FastAPI(title="GripTrack")
    app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
    app.mount("/static", StaticFiles(directory=BACKEND_DIR / "static"), name="static")

    app.include_router(home_router.router)
    app.include_router(auth_router.router)
    app.include_router(profile_router.router)

    @app.get("/health")
    def health(request: Request, session: Session = Depends(get_session)):
        db_alive = session.exec(text("SELECT 1")).one()[0] == 1
        return templates.TemplateResponse(
            request,
            "health.html",
            {"status": "ok" if db_alive else "degraded"},
        )

    return app


app = create_app()
