import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, text
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import LoginRateLimiter
from backend.db import get_session
from backend.routers import auth as auth_router
from backend.routers import climbs as climbs_router
from backend.routers import dashboard as dashboard_router
from backend.routers import guided_max_test as guided_max_test_router
from backend.routers import history as history_router
from backend.routers import home as home_router
from backend.routers import max_tests as max_tests_router
from backend.routers import plates as plates_router
from backend.routers import profile as profile_router
from backend.routers import pwa as pwa_router
from backend.routers import training_session as training_session_router
from backend.templating import templates

BACKEND_DIR = Path(__file__).parent

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # 'unsafe-inline' script-src is needed for the small inline handlers
    # (worksets glue, form autosubmits); everything else is same-origin only.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:"
    ),
}


def create_app() -> FastAPI:
    production = os.environ.get("GRIPTRACK_ENV", "dev") == "production"
    secret = os.environ.get("GRIPTRACK_SESSION_SECRET")
    if production and not secret:
        raise RuntimeError(
            "GRIPTRACK_SESSION_SECRET must be set when GRIPTRACK_ENV=production"
        )
    # The Android/Chaquopy WebView build (#93) embeds this same backend on
    # 127.0.0.1 with no service worker: WebView SW support is unreliable and
    # the offline caching is redundant when the server is already on-device.
    # base.html reads this global to skip both the SW registration script
    # and the (equally unnecessary) PWA manifest link. Unset/"0" behaves
    # exactly like today's web/PWA build — nothing changes for it.
    templates.env.globals["webview_build"] = (
        os.environ.get("GRIPTRACK_WEBVIEW_BUILD", "0") == "1"
    )

    app = FastAPI(title="GripTrack")
    app.state.login_limiter = LoginRateLimiter()
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret or "dev-only-secret",
        same_site="lax",
        https_only=production,
    )
    app.mount("/static", StaticFiles(directory=BACKEND_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @app.middleware("http")
    async def reject_cross_origin_posts(request: Request, call_next):
        # CSRF backstop on top of the SameSite=Lax cookie: browsers send an
        # Origin header on form posts — if it names a different host than
        # the one being posted to, refuse. Requests without an Origin
        # (curl, tests, same-site GET navigations) pass through.
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return PlainTextResponse(
                    "Cross-origin request rejected.", status_code=403
                )
        return await call_next(request)

    app.include_router(home_router.router)
    app.include_router(auth_router.router)
    app.include_router(profile_router.router)
    app.include_router(plates_router.router)
    app.include_router(max_tests_router.router)
    app.include_router(guided_max_test_router.router)
    app.include_router(training_session_router.router)
    app.include_router(climbs_router.router)
    app.include_router(history_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(pwa_router.router)

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
