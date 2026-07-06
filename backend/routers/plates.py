from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from backend import auth, plates
from backend.db import get_session
from backend.limits import MAX_PLATE_COUNT, MAX_PLATE_WEIGHT
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.post("/plates")
def set_plate(
    weight: float = Form(gt=0, le=MAX_PLATE_WEIGHT),
    count: int = Form(ge=0, le=MAX_PLATE_COUNT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    plates.set_plate(session, user, weight, count)
    return RedirectResponse("/plates", status_code=303)


@router.get("/plates")
def plates_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "plates.html",
        {"user": user, "items": plates.inventory_for(session, user)},
    )
