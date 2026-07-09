from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from backend import auth, guided_max_test, plates, training_log
from backend.db import get_session
from backend.limits import MAX_EDGE_MM, MAX_SET_NUMBER, MAX_WEIGHT
from backend.models import GripType, User
from backend.templating import templates

router = APIRouter()


def require_grip_type(session: Session, grip_type_id: int) -> None:
    if session.get(GripType, grip_type_id) is None:
        raise HTTPException(status_code=404, detail="Unknown grip type")


@router.get("/max-tests/guided")
def guided_test_form(
    request: Request,
    grip_type_id: int = Query(),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand is not None and hand not in ("left", "right"):
        return HTMLResponse("Hand must be left or right.", status_code=400)
    require_grip_type(session, grip_type_id)
    hands = training_log.hands_for(user, hand)
    default_estimate = guided_max_test.default_estimate(session, user)
    if len(hands) == 2:
        return templates.TemplateResponse(
            request,
            "guided_max_test_start_both.html",
            {
                "user": user,
                "grip_type_id": grip_type_id,
                "edge_mm": edge_mm,
                "date": date,
                "default_estimate": default_estimate,
            },
        )
    return templates.TemplateResponse(
        request,
        "guided_max_test_start.html",
        {
            "user": user,
            "grip_type_id": grip_type_id,
            "edge_mm": edge_mm,
            "date": date,
            "hand": hands[0],
            "default_estimate": default_estimate,
        },
    )


@router.post("/max-tests/guided")
def start_guided_test(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    estimate: float = Form(gt=0, le=MAX_WEIGHT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in ("left", "right"):
        return HTMLResponse("Hand must be left or right.", status_code=400)
    inventory = plates.inventory_for(session, user)
    suggested = guided_max_test.warmup_suggestion(estimate, inventory)
    return templates.TemplateResponse(
        request,
        "guided_max_test_step.html",
        {
            "user": user,
            "grip_type_id": grip_type_id,
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "estimate": estimate,
            "kind": "warmup",
            "set_number": 1,
            "reps": guided_max_test.WARMUP_REPS,
            "suggested": suggested,
            "needs_rating": False,
            "rest_hint": False,
        },
    )


@router.post("/max-tests/guided/both")
def start_guided_test_both(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    left_estimate: float = Form(gt=0, le=MAX_WEIGHT),
    right_estimate: float = Form(gt=0, le=MAX_WEIGHT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    inventory = plates.inventory_for(session, user)
    columns = guided_max_test.start_columns(left_estimate, right_estimate, inventory)
    return templates.TemplateResponse(
        request,
        "guided_max_test_step_both.html",
        {
            "user": user,
            "grip_type_id": grip_type_id,
            "edge_mm": edge_mm,
            "date": date,
            "columns": columns,
        },
    )


@router.post("/max-tests/guided/step")
def advance_guided_test(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    estimate: float = Form(gt=0, le=MAX_WEIGHT),
    kind: str = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    actual: float = Form(gt=0, le=MAX_WEIGHT),
    rating: str | None = Form(default=None),
    other_column: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in ("left", "right"):
        return HTMLResponse("Hand must be left or right.", status_code=400)
    inventory = plates.inventory_for(session, user)

    if other_column is not None:
        # Two-hand flow (#22): advance only `hand`; the other hand's ladder
        # state rides through as one opaque token the module owns.
        try:
            outcome, columns = guided_max_test.advance_two_hand(
                hand, kind, set_number, estimate, actual, rating,
                other_column, user.unit_pref, inventory,
            )
        except (guided_max_test.InvalidRating, guided_max_test.InvalidColumn):
            return HTMLResponse("Invalid ladder state.", status_code=400)
        if outcome == "done":
            training_log.record_max_weight_test(
                session, user, hand, grip_type_id, edge_mm, date, actual
            )
        return templates.TemplateResponse(
            request,
            "guided_max_test_step_both.html",
            {
                "user": user,
                "grip_type_id": grip_type_id,
                "edge_mm": edge_mm,
                "date": date,
                "columns": columns,
            },
        )

    # Classic single-hand flow (#21), unchanged, plus (#22) a sequential
    # hand-switch link on completion — mirroring the existing warmup
    # page's "Switch to {other} hand" convention.
    try:
        outcome, step = guided_max_test.advance(
            kind, set_number, estimate, actual, rating, user.unit_pref, inventory
        )
    except guided_max_test.InvalidRating:
        return HTMLResponse("Invalid rating.", status_code=400)
    if outcome == "done":
        training_log.record_max_weight_test(
            session, user, hand, grip_type_id, edge_mm, date, actual
        )
        switch_to = (
            ("right" if hand == "left" else "left")
            if user.hand_order_pref == "sequential"
            else None
        )
        return templates.TemplateResponse(
            request,
            "guided_max_test_done.html",
            {
                "user": user,
                "hand": hand,
                "weight": actual,
                "grip_type_id": grip_type_id,
                "edge_mm": edge_mm,
                "date": date,
                "other_hand": switch_to,
            },
        )
    # advance() only returns step=None alongside outcome="done", handled
    # (and returned from) above — reachable here, step is always a dict.
    assert step is not None
    return templates.TemplateResponse(
        request,
        "guided_max_test_step.html",
        {
            "user": user,
            "grip_type_id": grip_type_id,
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "estimate": estimate,
            **step,
        },
    )
