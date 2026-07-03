from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, text

from backend.db import get_session

BACKEND_DIR = Path(__file__).parent

templates = Jinja2Templates(directory=BACKEND_DIR / "templates")


def create_app() -> FastAPI:
    app = FastAPI(title="GripTrack")
    app.mount("/static", StaticFiles(directory=BACKEND_DIR / "static"), name="static")

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
