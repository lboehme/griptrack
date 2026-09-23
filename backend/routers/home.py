from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from backend import auth
from backend.db import get_session
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.get("/")
def home(
    request: Request,
    user: User | None = Depends(auth.optional_user),
    session: Session = Depends(get_session),
):
    # Renders for everyone; auth.optional_user hides the session-cookie
    # inspection (and the revoked-session check), so the home page never
    # greets a revoked session as logged-in.
    if (
        request.app.state.webview_build
        and user is None
        and not auth.any_user_exists(session)
    ):
        # WebView build, no device user yet: first run replaces both the
        # anonymous landing card and registration (ADR-0013).
        return RedirectResponse("/welcome", status_code=303)
    return templates.TemplateResponse(request, "home.html", {"user": user})
