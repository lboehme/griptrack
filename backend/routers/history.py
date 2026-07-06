from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.models import Climb, User
from backend.templating import templates

router = APIRouter()


@router.get("/history")
def history_page(
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
        "history.html",
        {
            "user": user,
            "history": training_log.session_history(session, user),
            "grip_names": training_log.grip_names(session),
            "climbs": climbs,
        },
    )
