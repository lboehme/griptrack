from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from backend import auth
from backend.analytics import parse_boulder_grade
from backend.db import get_session
from backend.models import CLIMB_STYLES, Climb, User
from backend.templating import templates

router = APIRouter()

# New climbs are always logged as boulder (sport-climb logging was dropped —
# see issue #55; the discipline column and existing sport rows are untouched
# so history keeps rendering them).
NEW_CLIMB_DISCIPLINE = "boulder"

GRADE_NOT_RECOGNIZED_MESSAGE = (
    "Climb logged, but the grade wasn't recognized — this climb won't "
    "appear in the strength/grade correlation."
)


def _climbs_for(session: Session, user: User) -> list[Climb]:
    return session.exec(
        select(Climb)
        .where(Climb.user_id == user.id)
        .order_by(Climb.date.desc(), Climb.id.desc())
    ).all()


@router.get("/climbs")
def climbs_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "climbs.html",
        {
            "user": user,
            "climbs": _climbs_for(session, user),
            "styles": CLIMB_STYLES,
            "today": date_type.today().isoformat(),
        },
    )


@router.post("/climbs")
def log_climb(
    request: Request,
    date: date_type = Form(),
    grade: str = Form(min_length=1),
    style: str = Form(),
    notes: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if style not in CLIMB_STYLES:
        return HTMLResponse(
            "Style must be one of: " + ", ".join(CLIMB_STYLES), status_code=400
        )
    session.add(
        Climb(
            user_id=user.id,
            date=date,
            discipline=NEW_CLIMB_DISCIPLINE,
            grade=grade,
            style=style,
            notes=notes,
        )
    )
    session.commit()

    if parse_boulder_grade(grade) is None:
        # Loud feedback per issue #55: render the page directly (instead of
        # the usual redirect) with a banner, rather than silently excluding
        # this climb from the correlation.
        return templates.TemplateResponse(
            request,
            "climbs.html",
            {
                "user": user,
                "climbs": _climbs_for(session, user),
                "styles": CLIMB_STYLES,
                "today": date_type.today().isoformat(),
                "grade_warning": GRADE_NOT_RECOGNIZED_MESSAGE,
            },
        )
    return RedirectResponse("/climbs", status_code=303)
