from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from backend import auth
from backend.db import get_session
from backend.models import CLIMB_DISCIPLINES, CLIMB_STYLES, Climb, User
from backend.templating import templates

router = APIRouter()


@router.get("/climbs")
def climbs_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    climbs = session.exec(
        select(Climb)
        .where(Climb.user_id == user.id)
        .order_by(Climb.date.desc(), Climb.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "climbs.html",
        {
            "user": user,
            "climbs": climbs,
            "disciplines": CLIMB_DISCIPLINES,
            "styles": CLIMB_STYLES,
            "today": date_type.today().isoformat(),
        },
    )


@router.post("/climbs")
def log_climb(
    date: date_type = Form(),
    discipline: str = Form(),
    grade: str = Form(min_length=1),
    style: str = Form(),
    notes: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if discipline not in CLIMB_DISCIPLINES:
        return HTMLResponse("Discipline must be boulder or sport.", status_code=400)
    if style not in CLIMB_STYLES:
        return HTMLResponse(
            "Style must be one of: " + ", ".join(CLIMB_STYLES), status_code=400
        )
    session.add(
        Climb(
            user_id=user.id,
            date=date,
            discipline=discipline,
            grade=grade,
            style=style,
            notes=notes,
        )
    )
    session.commit()
    return RedirectResponse("/climbs", status_code=303)
