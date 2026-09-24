from datetime import date as date_type

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth, climbing
from backend.db import get_session
from backend.limits import MAX_GRADE_LENGTH, MAX_NOTES_LENGTH
from backend.models import User

router = APIRouter()


@router.get("/climbs")
def climbs_page(user: User = Depends(auth.current_user)):
    """The climb form moved into the ＋ Log sheet (#149); the climb list
    lives on /history."""
    return RedirectResponse("/?log=climb", status_code=303)


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
        return RedirectResponse("/?saved=climb&grade_warning=1", status_code=303)
    return RedirectResponse("/?saved=climb", status_code=303)

