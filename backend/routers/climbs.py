from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from backend import auth
from backend.analytics import parse_boulder_grade
from backend.db import get_session
from backend.limits import MAX_GRADE_LENGTH, MAX_NOTES_LENGTH
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


def climbs_newest_first(session: Session, user: User) -> list[Climb]:
    """A user's climbs, newest first — the one query both the climbs page
    and the history page render from, so their ordering can't drift."""
    return list(
        session.exec(
            select(Climb)
            .where(Climb.user_id == user.id)
            .order_by(Climb.date.desc(), Climb.id.desc())
        ).all()
    )


@router.get("/climbs")
def climbs_page(
    request: Request,
    grade_warning: bool = Query(default=False),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "climbs.html",
        {
            "user": user,
            "climbs": climbs_newest_first(session, user),
            "styles": CLIMB_STYLES,
            "today": date_type.today().isoformat(),
            # The flag rides across the POST-redirect-GET; the message text
            # is a server-side constant, never echoed from the query string.
            "grade_warning": GRADE_NOT_RECOGNIZED_MESSAGE if grade_warning else None,
        },
    )


@router.post("/climbs")
def log_climb(
    date: date_type = Form(),
    grade: str = Form(min_length=1, max_length=MAX_GRADE_LENGTH),
    style: str = Form(),
    notes: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
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
        # Loud feedback per issue #55, without breaking POST-redirect-GET
        # (a refresh must not re-POST a duplicate climb): redirect with a
        # flag that the GET handler turns into the banner.
        return RedirectResponse("/climbs?grade_warning=1", status_code=303)
    return RedirectResponse("/climbs", status_code=303)
