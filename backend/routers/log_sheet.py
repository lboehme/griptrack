"""The ＋ Log sheet (#149): quick capture of a climb, bodyweight, or a
tweak from any tab-bar page. Shallow adapters over backend.today /
backend.climbing / backend.training_log.

Every save answers two ways: with HX-Request, the sheet slot's new content
(a toast) plus an HX-Trigger so Today can refresh in place; without it, a
303 back to Today carrying a `saved=` flag (POST-redirect-GET -- a refresh
never re-posts)."""

from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth, climbing, today, training_log
from backend.db import get_session
from backend.limits import MAX_GRADE_LENGTH, MAX_NOTES_LENGTH, MAX_WEIGHT
from backend.models import User
from backend.templating import templates

router = APIRouter()

LOGGED_EVENT = "griptrack-logged"


def _saved(request: Request, tab: str, grade_warning: str | None = None):
    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(
            request,
            "_log_toast.html",
            {"toast": today.SAVED_MESSAGES[tab], "grade_warning": grade_warning},
        )
        response.headers["HX-Trigger"] = LOGGED_EVENT
        return response
    url = f"/?saved={tab}" + ("&grade_warning=1" if grade_warning else "")
    return RedirectResponse(url, status_code=303)


@router.get("/log/sheet")
def log_sheet(
    request: Request,
    tab: str = Query(default="climb", max_length=16),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The sheet as an htmx fragment, swapped into base.html's sheet slot
    (no hx-push-url: opening it never adds a history entry)."""
    return templates.TemplateResponse(
        request,
        "_log_sheet.html",
        {"user": user, "sheet": today.sheet_view(session, user, tab, date_type.today())},
    )


@router.post("/log/climb")
def log_climb(
    request: Request,
    grade: str = Form(min_length=1, max_length=MAX_GRADE_LENGTH),
    grade_other: str | None = Form(default=None, max_length=MAX_GRADE_LENGTH),
    style: str = Form(),
    when: str = Form(default="today", max_length=16),
    today_date: date_type = Form(alias="today"),
    pick_date: date_type | None = Form(default=None),
    notes: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    try:
        grade_text = today.resolve_climb_grade(grade, grade_other)
        climb_date = today.resolve_log_date(when, today_date, pick_date)
        _climb, recognized = climbing.log_climb(
            session=session, user=user, date=climb_date, grade=grade_text,
            style=style, notes=notes,
        )
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    warning = None if recognized else climbing.GRADE_NOT_RECOGNIZED_MESSAGE
    return _saved(request, "climb", warning)


@router.post("/log/bodyweight")
def log_bodyweight(
    request: Request,
    date: date_type = Form(),
    weight: float = Form(gt=0, le=MAX_WEIGHT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_log.log_bodyweight(session, user, date, weight)
    return _saved(request, "bodyweight")


@router.post("/log/tweak")
def log_tweak(
    request: Request,
    date: date_type = Form(),
    hand: str = Form(max_length=8),
    severity: int = Form(ge=1, le=3),
    note: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    try:
        today.log_tweak(session, user, date, hand, severity, note)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return _saved(request, "tweak")
