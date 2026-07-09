from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from backend.db import get_session
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    # Same session-generation check as auth.current_user, but anonymous
    # rather than 401 on failure — the home page renders for everyone,
    # it just must not greet a revoked session as logged-in.
    user = session.get(User, request.session.get("user_id"))
    if user is not None and request.session.get("session_version") != user.session_version:
        user = None
    return templates.TemplateResponse(request, "home.html", {"user": user})
