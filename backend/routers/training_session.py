from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.models import GripType, User
from backend.templating import templates

router = APIRouter()


@router.post("/session/check")
def check_warmup_step(
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0),
    date: date_type = Form(),
    hand: str = Form(),
    step_index: int = Form(ge=0),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_session = training_log.start_or_get_session(session, user, date)
    training_log.record_warmup_check(session, training_session, hand, step_index)
    return RedirectResponse(
        f"/session/warmup?grip_type_id={grip_type_id}&edge_mm={edge_mm}"
        f"&date={date}&hand={hand}",
        status_code=303,
    )


@router.get("/session/new")
def new_session_form(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    grip_types = session.exec(select(GripType).order_by(GripType.name)).all()
    last_used = training_log.last_used_combination(session, user)
    return templates.TemplateResponse(
        request,
        "new_session.html",
        {
            "user": user,
            "grip_types": grip_types,
            "default_grip_type_id": last_used[0] if last_used else None,
            "default_edge_mm": last_used[1] if last_used else "",
            "today": date_type.today().isoformat(),
        },
    )


@router.get("/session/warmup")
def warmup_page(
    request: Request,
    grip_type_id: int = Query(),
    edge_mm: int = Query(gt=0),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    grip = session.get(GripType, grip_type_id)
    # "alternating" trains both hands side by side; "sequential" does one
    # hand's full flow at a time (default left, ?hand= for the other).
    if user.hand_order_pref == "sequential":
        hands = [hand if hand in ("left", "right") else "left"]
    else:
        hands = ["left", "right"]
    plans = {
        h: training_log.compute_ramp_plan(session, user, h, grip_type_id, edge_mm)
        for h in hands
    }
    untested_hands = [h for h, plan in plans.items() if plan is None]
    steps = []
    if not untested_hands:
        first_plan = plans[hands[0]]
        steps = [
            {"index": index, "percent": first_plan[index]["percent"]}
            for index in range(len(first_plan))
        ]
    training_session = training_log.find_session(session, user, date)
    checks = training_log.warmup_checks(session, training_session)
    return templates.TemplateResponse(
        request,
        "warmup.html",
        {
            "user": user,
            "grip": grip,
            "edge_mm": edge_mm,
            "date": date,
            "untested_hands": untested_hands,
            "plans": plans,
            "steps": steps,
            "hands": hands,
            "training_session": training_session,
            "checks": checks,
        },
    )
