"""WebView-build-only routes (ADR-0013, #145): device sign-in and the
first-run flow that replaces registration on a single-user on-device
install. `backend.main.create_app` only includes this router when
`GRIPTRACK_WEBVIEW_BUILD=1` -- in the server build none of these paths
exist (404), same as any other undefined route.

Shallow HTTP adapters only; the actual logic (token compare, device-user
creation) lives in `backend.auth` per the module-design convention.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth, plates
from backend.db import get_session
from backend.limits import MAX_NAME_LENGTH
from backend.models import VALID_HAND_ORDER_PREFS, VALID_UNITS, User
from backend.templating import templates

router = APIRouter()

# DoS/sanity bounds on the two device-login form fields -- generous for a
# urlsafe-base64 32-byte token (~43 chars) and a same-origin relative path.
MAX_DEVICE_TOKEN_LENGTH = 512
MAX_NEXT_LENGTH = 2048

# Signed-session flag set only by a successful /device-login before first
# run. Without it, /welcome is refused: any app on the phone can reach the
# loopback port, but only the shell holds the device token (ADR-0013).
FIRST_RUN_GRANT = "first_run_grant"


def _safe_next(next: str | None) -> str | None:
    """A `next` value is only ever honored if it's a same-origin relative
    path: starts with a single "/" (not "//" or "/\\", which a browser or
    WebView can interpret as protocol-relative -- i.e. off-origin) and
    carries no scheme. Anything else (None, an absolute URL, a
    protocol-relative URL) falls back to the caller's default."""
    if not next:
        return None
    if not next.startswith("/") or next.startswith(("//", "/\\")):
        return None
    if ":" in next:
        return None
    return next


@router.post("/device-login")
def device_login(
    request: Request,
    token: str = Form(default="", max_length=MAX_DEVICE_TOKEN_LENGTH),
    next: str | None = Form(default=None, max_length=MAX_NEXT_LENGTH),
    session: Session = Depends(get_session),
):
    limiter = request.app.state.login_limiter
    client_key = request.client.host if request.client else "unknown"
    if limiter.blocked(client_key):
        return HTMLResponse(
            "Too many attempts. Wait a minute and try again.", status_code=429
        )

    if not auth.device_token_valid(token):
        limiter.record_failure(client_key)
        return HTMLResponse("Invalid device token.", status_code=403)

    user = auth.device_login(session, token)
    if user is None:
        # Correct token, no user yet: grant the one-time first-run step.
        # Only the shell can read the token, so only it can reach /welcome.
        request.session[FIRST_RUN_GRANT] = True
        return RedirectResponse("/welcome", status_code=303)

    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    destination = _safe_next(next) or "/"
    return RedirectResponse(destination, status_code=303)


@router.get("/welcome")
def welcome_start(request: Request, session: Session = Depends(get_session)):
    if auth.any_user_exists(session):
        return RedirectResponse("/", status_code=303)
    if not request.session.get(FIRST_RUN_GRANT):
        return _first_run_refused()
    return templates.TemplateResponse(
        request, "welcome_start.html", {"hide_tabbar": True}
    )


def _first_run_refused() -> HTMLResponse:
    return HTMLResponse("Open GripTrack from the app to set it up.", status_code=403)


@router.post("/welcome")
def welcome_create(
    request: Request,
    name: str | None = Form(default=None, max_length=MAX_NAME_LENGTH),
    unit_pref: str = Form(default="kg"),
    hand_order_pref: str = Form(default="alternating"),
    session: Session = Depends(get_session),
):
    if auth.any_user_exists(session):
        # Idempotent: a refresh or double-submit after the device user
        # already exists just rejoins the app instead of erroring.
        return RedirectResponse("/", status_code=303)
    if not request.session.get(FIRST_RUN_GRANT):
        return _first_run_refused()
    if unit_pref not in VALID_UNITS:
        return HTMLResponse("Unit must be kg or lbs.", status_code=400)
    if hand_order_pref not in VALID_HAND_ORDER_PREFS:
        return HTMLResponse("Invalid hand order preference.", status_code=400)

    try:
        user = auth.create_device_user(
            session, name=name, unit_pref=unit_pref, hand_order_pref=hand_order_pref
        )
    except auth.DeviceUserExistsError:
        # Idempotent: a refresh or double-submit after the device user
        # already exists just rejoins the app instead of erroring.
        return RedirectResponse("/", status_code=303)
    except auth.RegistrationError as error:
        return HTMLResponse(str(error), status_code=400)

    request.session.pop(FIRST_RUN_GRANT, None)
    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    return RedirectResponse("/welcome/plates", status_code=303)


@router.get("/welcome/plates")
def welcome_plates(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "welcome_plates.html",
        {
            "user": user,
            "rack": plates.rack_view(session, user),
            "back": "/welcome/plates",
            # First run is a story, not a tab screen (#149): no tab bar.
            "hide_tabbar": True,
        },
    )


@router.get("/welcome/test")
def welcome_test(request: Request, user: User = Depends(auth.current_user)):
    return templates.TemplateResponse(
        request, "welcome_test.html", {"user": user, "hide_tabbar": True}
    )
