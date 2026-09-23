from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth
from backend.db import get_session
from backend.limits import MAX_NAME_LENGTH
from backend.models import User
from backend.templating import templates

# Registered unconditionally -- login/logout stay meaningful in both builds
# (the WebView build's device sign-in still goes through the same session
# cookie machinery; see backend.routers.device_auth for /device-login).
router = APIRouter()

# Registered only for the server build (ADR-0013, #145): invite-only
# registration, invite generation, and admin password reset protect a
# shared server (ADR-0004). On a single-user on-device install they protect
# nothing, so main.create_app() only includes this router when
# GRIPTRACK_WEBVIEW_BUILD is unset -- in the WebView build these paths are
# simply never registered (404), same as any other undefined route. Nothing
# is deleted: the self-hosting path (ADR-0006) still needs it.
server_only_router = APIRouter()


@server_only_router.post("/invites")
def create_invite(
    request: Request,
    user: User = Depends(auth.require_admin),
    session: Session = Depends(get_session),
):
    invite = auth.generate_invite(session, user)
    return templates.TemplateResponse(
        request, "invite.html", {"invite": invite, "user": user}
    )


@server_only_router.post("/admin/reset-password")
def admin_reset_password(
    email: str = Form(),
    new_password: str = Form(),
    admin: User = Depends(auth.require_admin),
    session: Session = Depends(get_session),
):
    user = auth.reset_password(session, email, new_password)
    if user is None:
        return HTMLResponse("No user with that email.", status_code=404)
    return RedirectResponse("/", status_code=303)


@router.get("/login")
def login_page(request: Request, session: Session = Depends(get_session)):
    if request.app.state.webview_build:
        # No password login in the WebView build (ADR-0013) -- device
        # sign-in is the only way in, and first run replaces registration.
        destination = "/welcome" if not auth.any_user_exists(session) else "/"
        return RedirectResponse(destination, status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    session: Session = Depends(get_session),
):
    limiter = request.app.state.login_limiter
    client_key = request.client.host if request.client else "unknown"
    if limiter.blocked(client_key):
        return HTMLResponse(
            "Too many attempts. Wait a minute and try again.", status_code=429
        )
    user = auth.authenticate(session, email.strip().lower(), password)
    if user is None:
        limiter.record_failure(client_key)
        return HTMLResponse("Wrong email or password.", status_code=401)
    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@server_only_router.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@server_only_router.post("/register")
def register(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    invite_code: str | None = Form(default=None),
    unit_pref: str = Form(default="kg"),
    name: str | None = Form(default=None, max_length=MAX_NAME_LENGTH),
    session: Session = Depends(get_session),
):
    limiter = request.app.state.login_limiter
    client_key = request.client.host if request.client else "unknown"
    if limiter.blocked(client_key):
        return HTMLResponse(
            "Too many attempts. Wait a minute and try again.", status_code=429
        )

    try:
        user = auth.register_user(
            session, email, password, invite_code, unit_pref, name
        )
    except auth.RegistrationError as error:
        limiter.record_failure(client_key)
        return HTMLResponse(str(error), status_code=400)
    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    return RedirectResponse("/", status_code=303)
