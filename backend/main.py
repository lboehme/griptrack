import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, text
from starlette.middleware.sessions import SessionMiddleware

from backend import auth
from backend.auth import LoginRateLimiter
from backend.db import get_session
from backend.routers import auth as auth_router
from backend.routers import climbs as climbs_router
from backend.routers import device_auth as device_auth_router
from backend.routers import guided_max_test as guided_max_test_router
from backend.routers import home as home_router
from backend.routers import log_sheet as log_sheet_router
from backend.routers import max_tests as max_tests_router
from backend.routers import plates as plates_router
from backend.routers import profile as profile_router
from backend.routers import progress as progress_router
from backend.routers import pwa as pwa_router
from backend.routers import settings as settings_router
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
    webview_build = os.environ.get("GRIPTRACK_WEBVIEW_BUILD", "0") == "1"
    templates.env.globals["webview_build"] = webview_build

    app = FastAPI(title="GripTrack")
    app.state.login_limiter = LoginRateLimiter()
    # Stashed on app.state (not just the template global above) so routers
    # can branch on it too -- see backend.routers.auth's GET /login and
    # backend.routers.device_auth's WebView-only routes.
    app.state.webview_build = webview_build
    # A single-user on-device install has no "remember me" flow -- device
    # sign-in (ADR-0013) is what re-establishes the session cookie on every
    # cold start anyway, so the cookie itself can just outlive any real gap
    # between launches. The server build keeps Starlette's own default
    # (1209600s / 14 days) verbatim.
    session_max_age = (
        auth.DEVICE_SESSION_MAX_AGE_SECONDS if webview_build else 1209600
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret or "dev-only-secret",
        same_site="lax",
        https_only=production,
        max_age=session_max_age,
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
    app.include_router(log_sheet_router.router)
    app.include_router(auth_router.router)
    if webview_build:
        # First run + device sign-in replace registration (ADR-0013) --
        # only meaningful, and only registered, on-device.
        app.include_router(device_auth_router.router)
    else:
        # Invite-only registration, invites, admin password reset: a
        # shared-server concern (ADR-0004) with nothing to protect on a
        # single-user on-device install, so left unregistered there (404).
        app.include_router(auth_router.server_only_router)
    app.include_router(settings_router.router)
    app.include_router(profile_router.router)
    app.include_router(plates_router.router)
    app.include_router(max_tests_router.router)
    app.include_router(guided_max_test_router.router)
    app.include_router(training_session_router.router)
    app.include_router(climbs_router.router)
    app.include_router(progress_router.router)
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
