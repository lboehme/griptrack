from fastapi import APIRouter, Depends, Request

from backend import auth
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.get("/")
def home(
    request: Request,
    user: User | None = Depends(auth.optional_user),
):
    # Renders for everyone; auth.optional_user hides the session-cookie
    # inspection (and the revoked-session check), so the home page never
    # greets a revoked session as logged-in.
    return templates.TemplateResponse(request, "home.html", {"user": user})
