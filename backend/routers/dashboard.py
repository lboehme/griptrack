from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from backend import analytics, auth
from backend.db import get_session
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.get("/dashboard")
def dashboard_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    view = analytics.dashboard_view(session, user)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            **view,
        },
    )
