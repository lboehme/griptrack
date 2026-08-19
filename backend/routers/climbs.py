from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth, climbing
from backend.db import get_session
from backend.limits import MAX_GRADE_LENGTH, MAX_NOTES_LENGTH
from backend.models import CLIMB_STYLES, User
from backend.templating import templates

router = APIRouter()

GRADE_NOT_RECOGNIZED_MESSAGE = (
    "Climb logged, but the grade wasn't recognized — this climb won't "
    "appear in the strength/grade correlation."
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
            "climbs": climbing.climbs_newest_first(session, user),
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
    try:
        _climb, recognized_grade = climbing.log_climb(
            session=session,
            user=user,
            date=date,
            grade=grade,
            style=style,
            notes=notes,
        )
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)

    if not recognized_grade:
        # Loud feedback per issue #55, without breaking POST-redirect-GET
        # (a refresh must not re-POST a duplicate climb): redirect with a
        # flag that the GET handler turns into the banner.
        return RedirectResponse("/climbs?grade_warning=1", status_code=303)
    return RedirectResponse("/climbs", status_code=303)

