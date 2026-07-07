from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from backend import auth, guided_max_test, plates, training_log
from backend.db import get_session
from backend.limits import MAX_EDGE_MM, MAX_REPS, MAX_SET_NUMBER, MAX_WEIGHT
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
    columns = [
        guided_max_test.warmup_column("left", left_estimate, inventory),
        guided_max_test.warmup_column("right", right_estimate, inventory),
    ]
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
    other_hand: str | None = Form(default=None),
    other_status: str | None = Form(default=None),
    other_kind: str | None = Form(default=None),
    other_set_number: int | None = Form(default=None, ge=1, le=MAX_SET_NUMBER),
    other_reps: int | None = Form(default=None, ge=1, le=MAX_REPS),
    other_suggested: float | None = Form(default=None, gt=0, le=MAX_WEIGHT),
    other_needs_rating: str | None = Form(default=None),
    other_rest_hint: str | None = Form(default=None),
    other_estimate: float | None = Form(default=None, gt=0, le=MAX_WEIGHT),
    other_weight: float | None = Form(default=None, gt=0, le=MAX_WEIGHT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in ("left", "right"):
        return HTMLResponse("Hand must be left or right.", status_code=400)
    inventory = plates.inventory_for(session, user)
    try:
        outcome, step = guided_max_test.advance(
            kind, set_number, estimate, actual, rating, user.unit_pref, inventory
        )
    except guided_max_test.InvalidRating:
        return HTMLResponse("Invalid rating.", status_code=400)

    if other_hand is None:
        # Classic single-hand flow (#21), unchanged, plus (#22) a sequential
        # hand-switch link on completion — mirroring the existing warmup
        # page's "Switch to {other} hand" convention.
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

    # Two-hand flow (#22): advance only `hand`; the other hand's state
    # travels through as hidden fields and is echoed back unchanged — its
    # own ladder was never touched by this request.
    if outcome == "done":
        training_log.record_max_weight_test(
            session, user, hand, grip_type_id, edge_mm, date, actual
        )
        this_column = guided_max_test.done_column(hand, actual)
    else:
        this_column = guided_max_test.active_column(hand, estimate=estimate, **step)

    if other_status == "done":
        other_column = guided_max_test.done_column(other_hand, other_weight)
    else:
        other_column = guided_max_test.active_column(
            other_hand,
            other_kind,
            other_set_number,
            other_reps,
            other_suggested,
            other_needs_rating == "True",
            other_rest_hint == "True",
            other_estimate,
        )
    columns = guided_max_test.ordered_columns(hand, this_column, other_column)
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
