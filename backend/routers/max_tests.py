from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.limits import MAX_EDGE_MM, MAX_WEIGHT
from backend.models import GripType, User

router = APIRouter()

# The Maxes detail page under Progress (#150); GET /max-tests redirects there.
MAXES_PAGE = "/progress/maxes"


@router.post("/max-tests")
def log_max_test(
    hand: str = Form(),
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    weight: float = Form(gt=0, le=MAX_WEIGHT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in ("left", "right"):
        return HTMLResponse("Hand must be left or right.", status_code=400)
    if session.get(GripType, grip_type_id) is None:
        return HTMLResponse("Unknown grip type.", status_code=400)
    training_log.record_max_weight_test(
        session, user, hand, grip_type_id, edge_mm, date, weight
    )
    return RedirectResponse(MAXES_PAGE, status_code=303)


@router.post("/grip-types")
def add_grip_type(
    name: str = Form(min_length=1, max_length=60),
    admin: User = Depends(auth.require_admin),
    session: Session = Depends(get_session),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/profile", status_code=303)
    existing = session.exec(select(GripType).where(GripType.name == name)).first()
    if existing is None:
        session.add(GripType(name=name))
        session.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/max-tests/{test_id}/void")
def void_max_test(
    test_id: int,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    test = training_log.void_max_weight_test(session, user, test_id)
    if test is None:
        raise HTTPException(status_code=403, detail="Cannot void this test")
    return RedirectResponse(MAXES_PAGE, status_code=303)
