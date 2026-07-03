from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from backend import auth
from backend.db import get_session
from backend.models import BodyWeightLog, User
from backend.templating import templates

router = APIRouter()


def latest_bodyweight(session: Session, user: User) -> BodyWeightLog | None:
    return session.exec(
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == user.id)
        .order_by(BodyWeightLog.date.desc(), BodyWeightLog.id.desc())
    ).first()


@router.get("/profile")
def profile(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "current_bodyweight": latest_bodyweight(session, user),
            "today": date_type.today().isoformat(),
        },
    )


@router.post("/profile/bodyweight")
def log_bodyweight(
    date: date_type = Form(),
    weight: float = Form(gt=0),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    session.add(BodyWeightLog(user_id=user.id, date=date, weight=weight))
    session.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile")
def update_profile(
    hand_order_pref: str = Form(),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand_order_pref not in ("alternating", "sequential"):
        return HTMLResponse("Invalid hand order preference.", status_code=400)
    user.hand_order_pref = hand_order_pref
    session.add(user)
    session.commit()
    return RedirectResponse("/profile", status_code=303)
