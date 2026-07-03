from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.models import GripType, User
from backend.templating import templates

router = APIRouter()


def hands_for(user: User, hand: str | None) -> list[str]:
    # "alternating" trains both hands side by side; "sequential" does one
    # hand's full flow at a time (default left, ?hand= for the other).
    if user.hand_order_pref == "sequential":
        return [hand if hand in ("left", "right") else "left"]
    return ["left", "right"]


@router.get("/session/worksets")
def worksets_page(
    request: Request,
    grip_type_id: int = Query(),
    edge_mm: int = Query(gt=0),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    sets: int | None = Query(default=None, ge=1),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    grip = session.get(GripType, grip_type_id)
    hands = hands_for(user, hand)
    protocol = training_log.get_protocol(session, user)
    saved = {
        (ws.hand, ws.set_number): ws
        for ws in training_log.worksets_for_combo(
            session, user, grip_type_id, edge_mm, date
        )
    }
    current_max = {
        h: training_log.compute_current_max(session, user, h, grip_type_id, edge_mm)
        for h in hands
    }
    highest_saved = max((n for _, n in saved), default=0)
    needed_rows = max(protocol.default_work_sets, highest_saved)
    row_count = max(needed_rows, sets or 0)
    # Extra empty rows (from "add another set") can be dismissed again.
    removable_to = row_count - 1 if row_count > needed_rows else None
    return templates.TemplateResponse(
        request,
        "worksets.html",
        {
            "user": user,
            "grip": grip,
            "edge_mm": edge_mm,
            "date": date,
            "hands": hands,
            "set_numbers": list(range(1, row_count + 1)),
            "saved": saved,
            "current_max": current_max,
            "default_reps": protocol.base_work_set_reps,
            "more_sets": row_count + 1,
            "removable_to": removable_to,
        },
    )


@router.post("/session/workset")
def save_work_set(
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0),
    date: date_type = Form(),
    hand: str = Form(),
    set_number: int = Form(ge=1),
    weight: float = Form(gt=0),
    reps: int = Form(ge=1),
    rpe: float | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if rpe is not None and not (1.0 <= rpe <= 10.0 and (rpe * 2) == int(rpe * 2)):
        return HTMLResponse(
            "RPE must be between 1 and 10 in 0.5 steps.", status_code=400
        )
    training_session = training_log.start_or_get_session(session, user, date)
    training_log.record_work_set(
        session, training_session, hand, grip_type_id, edge_mm, set_number,
        weight, reps, rpe,
    )
    return RedirectResponse(
        f"/session/worksets?grip_type_id={grip_type_id}&edge_mm={edge_mm}"
        f"&date={date}&hand={hand}",
        status_code=303,
    )


@router.post("/session/workset/delete")
def delete_work_set(
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0),
    date: date_type = Form(),
    hand: str = Form(),
    set_number: int = Form(ge=1),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_session = training_log.find_session(session, user, date)
    if training_session is not None:
        training_log.delete_work_set(
            session, training_session, hand, grip_type_id, edge_mm, set_number
        )
    return RedirectResponse(
        f"/session/worksets?grip_type_id={grip_type_id}&edge_mm={edge_mm}"
        f"&date={date}&hand={hand}",
        status_code=303,
    )


@router.post("/session/check")
def check_warmup_step(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0),
    date: date_type = Form(),
    hand: str = Form(),
    step_index: int = Form(ge=0),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_session = training_log.start_or_get_session(session, user, date)
    training_log.toggle_warmup_check(session, training_session, hand, step_index)
    # htmx ticks stay on the page (no reload); plain form posts redirect.
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
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
            "history": training_log.session_history(session, user)[:8],
            "grip_names": {grip.id: grip.name for grip in grip_types},
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
