from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.limits import (
    MAX_EDGE_MM,
    MAX_NOTES_LENGTH,
    MAX_REPS,
    MAX_SESSION_NUMBER,
    MAX_SET_NUMBER,
    MAX_WEIGHT,
)
from backend.models import GripType, PainReport, User
from backend.templating import templates

router = APIRouter()


def combo_redirect(
    page: str,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str,
    session_number: int | None = None,
) -> RedirectResponse:
    """Back to a session page for the same (grip, edge, date, hand[, session_number])."""
    url = (
        f"/session/{page}?grip_type_id={grip_type_id}&edge_mm={edge_mm}"
        f"&date={date}&hand={hand}"
    )
    if session_number is not None:
        url += f"&session_number={session_number}"
    return RedirectResponse(url, status_code=303)


def require_grip_type(session: Session, grip_type_id: int) -> None:
    if session.get(GripType, grip_type_id) is None:
        raise HTTPException(status_code=404, detail="Unknown grip type")


def needs_creation_confirmation(
    session: Session,
    user: User,
    date: date_type,
    session_number: int | None,
) -> bool:
    """Whether this (date[, session_number]) has no TrainingSession yet AND
    the date is in the past — the explicit-past-session-creation gate (see
    CLAUDE.md: multi-session days). Today's date always creates implicitly,
    same as before this slice."""
    if not training_log.is_past_date(date):
        return False
    return training_log.find_session(session, user, date, session_number) is None


def confirm_creation_response(
    request: Request,
    user: User,
    page: str,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None,
    session_number: int | None,
):
    return templates.TemplateResponse(
        request,
        "session_confirm.html",
        {
            "user": user,
            "page": page,
            "grip_type_id": grip_type_id,
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "session_number": session_number,
        },
    )


@router.post("/session/create")
def create_session(
    request: Request,
    page: str = Form(),
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The explicit "create a session on this past date" confirmation
    (see needs_creation_confirmation) — the only place a past-dated
    session gets created without one already existing."""
    if page not in ("warmup", "worksets"):
        return HTMLResponse("Unknown page.", status_code=400)
    training_log.start_or_get_session(session, user, date, session_number)
    return combo_redirect(page, grip_type_id, edge_mm, date, hand or "", session_number)


@router.get("/session/worksets")
def worksets_page(
    request: Request,
    grip_type_id: int = Query(),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    sets: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Query(default=None, ge=1, le=MAX_SESSION_NUMBER),
    edit: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """edit=N is the Focus screen's Edit mode (issue #80): re-renders the
    same page with set N's saved values loaded into the hand cards instead
    of the normal in-progress set -- the no-JS degradation of tapping a
    COMPLETED row. Saving posts to the same /session/set as any other Set
    commit; Cancel is just a plain link back to this page without edit=."""
    require_grip_type(session, grip_type_id)
    if needs_creation_confirmation(session, user, date, session_number):
        return confirm_creation_response(
            request, user, "worksets", grip_type_id, edge_mm, date, hand,
            session_number,
        )
    view = training_log.worksets_view(
        session, user, grip_type_id, edge_mm, date, hand, sets, session_number, edit
    )
    return templates.TemplateResponse(
        request, "worksets.html", {"user": user, **view}
    )


@router.post("/session/workset")
def save_work_set(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    weight: float = Form(gt=0, le=MAX_WEIGHT),
    reps: int = Form(ge=1, le=MAX_REPS),
    rpe: float | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if rpe is not None and not (1.0 <= rpe <= 10.0 and (rpe * 2) == int(rpe * 2)):
        return HTMLResponse(
            "RPE must be between 1 and 10 in 0.5 steps.", status_code=400
        )
    training_session = training_log.start_or_get_session(
        session, user, date, session_number
    )
    training_log.record_work_set(
        session, training_session, hand, grip_type_id, edge_mm, set_number,
        weight, reps, rpe,
    )
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return combo_redirect("worksets", grip_type_id, edge_mm, date, hand, session_number)


@router.post("/session/set")
def save_focus_set(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    left_weight: float | None = Form(default=None),
    left_reps: int | None = Form(default=None),
    left_rpe: float | None = Form(default=None),
    right_weight: float | None = Form(default=None),
    right_reps: int | None = Form(default=None),
    right_rpe: float | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Set commit (docs/adr/0007-set-commit-over-per-cell-autosave.md):
    writes both hands' WorkSets for one set_number in a single atomic
    request instead of two calls to the per-hand /session/workset — a
    half-failure on flaky gym wifi must never log one hand and not the
    other.

    Every present hand's payload is fully validated (same bounds and RPE
    grid as /session/workset) *before* anything touches the session or the
    database, so an invalid or partial payload writes nothing at all. Once
    validation passes, both hands are staged with record_work_set(commit=
    False) and committed together in one transaction. Re-posting the same
    (session, hand, set_number) upserts in place (also the edit-mode path,
    #80) rather than duplicating."""
    raw = {
        "left": (left_weight, left_reps, left_rpe),
        "right": (right_weight, right_reps, right_rpe),
    }
    hands_payload: dict[str, tuple[float, int, float | None]] = {}
    for hand, (weight, reps, rpe) in raw.items():
        if weight is None and reps is None and rpe is None:
            continue  # this hand wasn't submitted (sequential hand order)
        if weight is None or reps is None:
            return HTMLResponse(
                f"{hand} hand needs both weight and reps.", status_code=400
            )
        if not (0 < weight <= MAX_WEIGHT):
            return HTMLResponse("Weight out of range.", status_code=400)
        if not (1 <= reps <= MAX_REPS):
            return HTMLResponse("Reps out of range.", status_code=400)
        if rpe is not None and not (1.0 <= rpe <= 10.0 and (rpe * 2) == int(rpe * 2)):
            return HTMLResponse(
                "RPE must be between 1 and 10 in 0.5 steps.", status_code=400
            )
        hands_payload[hand] = (weight, reps, rpe)

    if not hands_payload:
        return HTMLResponse(
            "At least one hand's weight and reps are required.", status_code=400
        )

    # Reject an unknown grip_type_id before any DB write, matching the GET
    # worksets page — otherwise an out-of-range id would 500 (or create an
    # orphan WorkSet row) instead of a clean 404.
    require_grip_type(session, grip_type_id)

    training_session = training_log.start_or_get_session(
        session, user, date, session_number
    )
    for hand, (weight, reps, rpe) in hands_payload.items():
        training_log.record_work_set(
            session, training_session, hand, grip_type_id, edge_mm, set_number,
            weight, reps, rpe, commit=False,
        )
    session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    redirect_hand = next(iter(hands_payload)) if len(hands_payload) == 1 else ""
    return combo_redirect(
        "worksets", grip_type_id, edge_mm, date, redirect_hand, session_number
    )


@router.post("/session/workset/delete")
def delete_work_set(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_log.delete_work_set(
            session, training_session, hand, grip_type_id, edge_mm, set_number
        )
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return combo_redirect("worksets", grip_type_id, edge_mm, date, hand, session_number)


@router.post("/session/estimate")
def save_session_estimate(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    weight: float = Form(gt=0, le=MAX_WEIGHT),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_session = training_log.start_or_get_session(
        session, user, date, session_number
    )
    training_log.record_session_estimate(
        session, training_session, hand, grip_type_id, edge_mm, weight
    )
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return combo_redirect("warmup", grip_type_id, edge_mm, date, hand, session_number)


@router.post("/session/check")
def check_warmup_step(
    request: Request,
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    step_index: int = Form(ge=0, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_session = training_log.start_or_get_session(
        session, user, date, session_number
    )
    training_log.toggle_warmup_check(session, training_session, hand, step_index)
    # htmx ticks stay on the page (no reload); plain form posts redirect.
    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return combo_redirect("warmup", grip_type_id, edge_mm, date, hand, session_number)


@router.post("/session/update")
def update_session(
    request: Request,
    date: date_type = Form(),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    notes: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
    is_deload: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Autosave endpoint for session-level fields. The form always posts
    both fields together, so a checkbox that's unchecked (and therefore
    omitted by the browser) is unambiguous: it means False."""
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_session.notes = notes or ""
        training_session.is_deload = (is_deload == "on")

        session.add(training_session)
        session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return RedirectResponse("/history", status_code=303)


@router.post("/session/pain-report")
def add_pain_report(
    request: Request,
    date: date_type = Form(),
    hand: str = Form(),
    severity: int = Form(ge=1, le=3),
    note: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in ("left", "right", "both"):
        return HTMLResponse("Hand must be left, right, or both.", status_code=400)
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        # One logical "tweak" per hand is one row — the severity select and
        # the note field autosave independently on the frontend, so this
        # must be an upsert keyed on (session, hand) rather than always
        # inserting, matching the autosave idiom everywhere else in the app.
        report = session.exec(
            select(PainReport)
            .where(PainReport.training_session_id == training_session.id)
            .where(PainReport.hand == hand)
        ).first()
        if report is None:
            report = PainReport(training_session_id=training_session.id, hand=hand)
        report.severity = severity
        report.note = note
        session.add(report)
        session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return RedirectResponse("/history", status_code=303)


@router.get("/session/new")
def new_session_form(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    grip_types = session.exec(select(GripType).order_by(GripType.name)).all()
    last_used = training_log.last_used_combination(session, user)
    today = date_type.today()
    # "Start a second session today" only appears once today already has
    # one — the server's own clock is close enough here (this is a display
    # affordance, not the client-local date correctness the date input
    # itself needs; see the local-date-default JS for that).
    today_session = training_log.find_session(session, user, today)
    return templates.TemplateResponse(
        request,
        "new_session.html",
        {
            "user": user,
            "grip_types": grip_types,
            "default_grip_type_id": last_used[0] if last_used else None,
            "default_edge_mm": last_used[1] if last_used else "",
            "today": today.isoformat(),
            "next_session_number_today": (
                today_session.session_number + 1 if today_session else None
            ),
            "history": training_log.session_history(session, user)[:8],
            "grip_names": training_log.grip_names(session),
            "grip_dimension_names": training_log.grip_dimension_names(session),
        },
    )


@router.get("/session/warmup")
def warmup_page(
    request: Request,
    grip_type_id: int = Query(),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    session_number: int | None = Query(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    require_grip_type(session, grip_type_id)
    if needs_creation_confirmation(session, user, date, session_number):
        return confirm_creation_response(
            request, user, "warmup", grip_type_id, edge_mm, date, hand,
            session_number,
        )
    view = training_log.warmup_view(
        session, user, grip_type_id, edge_mm, date, hand, session_number
    )
    return templates.TemplateResponse(
        request, "warmup.html", {"user": user, **view}
    )
