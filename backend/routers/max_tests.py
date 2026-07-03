from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.models import GripType, User
from backend.templating import templates

router = APIRouter()


@router.get("/max-tests")
def max_tests_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    grip_types = session.exec(select(GripType).order_by(GripType.name)).all()
    grip_names = {grip.id: grip.name for grip in grip_types}
    combos = [
        {**combo, "grip_name": grip_names[combo["grip_type_id"]]}
        for combo in training_log.tested_combinations(session, user)
    ]
    return templates.TemplateResponse(
        request,
        "max_tests.html",
        {"user": user, "grip_types": grip_types, "combos": combos},
    )


@router.post("/max-tests")
def log_max_test(
    hand: str = Form(),
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0),
    date: date_type = Form(),
    weight: float = Form(gt=0),
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
    return RedirectResponse("/max-tests", status_code=303)


@router.post("/grip-types")
def add_grip_type(
    name: str = Form(min_length=1),
    admin: User = Depends(auth.require_admin),
    session: Session = Depends(get_session),
):
    existing = session.exec(select(GripType).where(GripType.name == name)).first()
    if existing is None:
        session.add(GripType(name=name))
        session.commit()
    return RedirectResponse("/max-tests", status_code=303)
