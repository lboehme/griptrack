from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.models import GripType, User
from backend.templating import templates

router = APIRouter()


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
    view = training_log.worksets_view(
        session, user, grip_type_id, edge_mm, date, hand, sets
    )
    return templates.TemplateResponse(
        request, "worksets.html", {"user": user, **view}
    )


@router.post("/session/workset")
def save_work_set(
    request: Request,
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
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return RedirectResponse(
        f"/session/worksets?grip_type_id={grip_type_id}&edge_mm={edge_mm}"
        f"&date={date}&hand={hand}",
        status_code=303,
    )


@router.post("/session/workset/delete")
def delete_work_set(
    request: Request,
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
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
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
    view = training_log.warmup_view(session, user, grip_type_id, edge_mm, date, hand)
    return templates.TemplateResponse(
        request, "warmup.html", {"user": user, **view}
    )
