from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from backend.db import get_session
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    user = session.get(User, request.session.get("user_id"))
    return templates.TemplateResponse(request, "home.html", {"user": user})
