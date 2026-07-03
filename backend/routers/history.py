from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.models import Climb, GripType, User
from backend.templating import templates

router = APIRouter()


@router.get("/history")
def history_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    grip_names = {
        grip.id: grip.name for grip in session.exec(select(GripType)).all()
    }
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
            "grip_names": grip_names,
            "climbs": climbs,
        },
    )
