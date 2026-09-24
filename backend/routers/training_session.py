from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

from backend import auth, training_log
from backend.db import get_session
from backend.limits import (
    MAX_EDGE_MM,
    MAX_NOTES_LENGTH,
    MAX_REPS,
    MAX_ROW_ID,
    MAX_SESSION_NUMBER,
    MAX_SESSION_RPE,
    MAX_SET_NUMBER,
    MAX_WEIGHT,
    MIN_SESSION_RPE,
)
from backend.models import VALID_HANDS, User
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


def _undo_query_suffix(undo: dict | None) -> str:
    """The undo-after-delete affordance (issue #146 review item 2) has no
    server-side state of its own -- the deleted set's values ride along in
    the redirect's query string so the no-JS 303 -> GET /session/play round
    trip can still render the "Set N deleted [Undo]" banner once, from
    query params alone."""
    if not undo:
        return ""
    parts = [f"undo_set={undo['set_number']}"]
    for hand, vals in undo["hands"].items():
        parts.append(f"undo_{hand}_weight={vals['weight']}")
        parts.append(f"undo_{hand}_reps={vals['reps']}")
        if vals["rpe"] is not None:
            parts.append(f"undo_{hand}_rpe={vals['rpe']}")
    return "&" + "&".join(parts)


def play_redirect(
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None,
    session_number: int | None = None,
    sets: int | None = None,
    edit: int | None = None,
    undo: dict | None = None,
) -> RedirectResponse:
    """Back to /session/play for the same combo, preserving every query
    parameter a step might have been rendered with (issue #146: the no-JS
    fallback for every play action, and the /session/warmup, /session/worksets
    redirects)."""
    url = f"/session/play?grip_type_id={grip_type_id}&edge_mm={edge_mm}&date={date}"
    if hand:
        url += f"&hand={hand}"
    if session_number is not None:
        url += f"&session_number={session_number}"
    if sets is not None:
        url += f"&sets={sets}"
    if edit is not None:
        url += f"&edit={edit}"
    url += _undo_query_suffix(undo)
    return RedirectResponse(url, status_code=303)


def play_response(
    request: Request,
    user: User,
    session: Session,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None,
    session_number: int | None,
    sets: int | None = None,
    edit: int | None = None,
    undo: dict | None = None,
):
    """Every play action answers the same way (ADR-0014): with HX-Request,
    the next step's fragment; without it, a 303 back to /session/play so a
    plain form post still lands on the right step as a full page."""
    if request.headers.get("HX-Request"):
        view = training_log.play_view(
            session, user, grip_type_id, edge_mm, date, hand, session_number,
            sets, edit,
        )
        return templates.TemplateResponse(
            request, "_play_fragment.html", {"user": user, "undo": undo, **view}
        )
    return play_redirect(
        grip_type_id, edge_mm, date, hand, session_number, sets, edit, undo
    )


def _start_play(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    session_number: int | None,
    sets: int | None,
):
    try:
        return training_log.start_play_on_combo(
            session, user, grip_type_id, edge_mm, date, session_number, sets
        )
    except training_log.UnknownGripTypeError:
        raise HTTPException(status_code=404, detail="Unknown grip type") from None


def require_grip_type(session: Session, grip_type_id: int) -> None:
    try:
        training_log.require_grip_type(session, grip_type_id)
    except training_log.UnknownGripTypeError:
        raise HTTPException(status_code=404, detail="Unknown grip type") from None


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
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
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
    if page not in ("play", "warmup", "worksets"):
        return HTMLResponse("Unknown page.", status_code=400)
    training_log.start_or_get_session(session, user, date, session_number)
    if page == "play":
        return play_redirect(grip_type_id, edge_mm, date, hand, session_number)
    return combo_redirect(page, grip_type_id, edge_mm, date, hand or "", session_number)


@router.get("/session/worksets")
def worksets_page(
    request: Request,
    grip_type_id: int = Query(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    sets: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Query(default=None, ge=1, le=MAX_SESSION_NUMBER),
    edit: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Session play (#146, docs/adr/0014): /session/worksets is now just a
    redirect to /session/play, preserving every query parameter."""
    return play_redirect(grip_type_id, edge_mm, date, hand, session_number, sets, edit)


@router.post("/session/workset")
def save_work_set(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
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
    if hand not in VALID_HANDS:
        return HTMLResponse("Hand must be left or right.", status_code=400)
    if rpe is not None and not (1.0 <= rpe <= 10.0 and (rpe * 2) == int(rpe * 2)):
        return HTMLResponse(
            "RPE must be between 1 and 10 in 0.5 steps.", status_code=400
        )
    require_grip_type(session, grip_type_id)
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
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    hand: str | None = Form(default=None),
    editing: str | None = Form(default=None),
    sets: int | None = Form(default=None, ge=1, le=MAX_SET_NUMBER),
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

    Session play (#146): a normal (non-editing) commit also starts the rest
    step, per training_log.commit_focus_set / docs/adr/0014 orchestrator
    decision 1."""
    try:
        hands_payload = training_log.parse_hands_payload(
            left_weight, left_reps, left_rpe, right_weight, right_reps, right_rpe
        )
    except training_log.SetValidationError as e:
        return HTMLResponse(str(e), status_code=400)

    try:
        training_log.commit_focus_set(
            session, user, grip_type_id, edge_mm, date, set_number,
            session_number, hands_payload,
            editing=(editing == "true"), sets_hint=sets,
        )
    except training_log.UnknownGripTypeError:
        raise HTTPException(status_code=404, detail="Unknown grip type") from None

    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/set/delete")
def delete_focus_set(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    hand: str | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    require_grip_type(session, grip_type_id)
    training_session = training_log.find_session(session, user, date, session_number)
    deleted: dict = {}
    if training_session is not None:
        deleted = training_log.delete_set_and_renumber(
            session, training_session, grip_type_id, edge_mm, set_number
        )
    undo = {"set_number": set_number, "hands": deleted} if deleted else None
    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number,
        undo=undo,
    )


@router.post("/session/set/restore")
def restore_focus_set(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    hand: str | None = Form(default=None),
    left_weight: float | None = Form(default=None),
    left_reps: int | None = Form(default=None),
    left_rpe: float | None = Form(default=None),
    right_weight: float | None = Form(default=None),
    right_reps: int | None = Form(default=None),
    right_rpe: float | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Undo counterpart to /session/set/delete: re-inserts a deleted set at
    its original set_number (shifting higher sets back up) with the values
    the client held during the undo window. Same payload validation as
    /session/set."""
    try:
        hands_payload = training_log.parse_hands_payload(
            left_weight, left_reps, left_rpe, right_weight, right_reps, right_rpe
        )
    except training_log.SetValidationError as e:
        return HTMLResponse(str(e), status_code=400)

    try:
        training_log.restore_focus_set(
            session, user, grip_type_id, edge_mm, date, set_number,
            session_number, hands_payload,
        )
    except training_log.UnknownGripTypeError:
        raise HTTPException(status_code=404, detail="Unknown grip type") from None

    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/workset/delete")
def delete_work_set(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    set_number: int = Form(ge=1, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in VALID_HANDS:
        return HTMLResponse("Hand must be left or right.", status_code=400)
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
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    weight: float = Form(gt=0, le=MAX_WEIGHT),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    sets: int | None = Form(default=None, ge=1, le=MAX_SET_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in VALID_HANDS:
        return HTMLResponse("Hand must be left or right.", status_code=400)
    training_session = _start_play(
        session, user, grip_type_id, edge_mm, date, session_number, sets
    )
    training_log.record_session_estimate(
        session, training_session, hand, grip_type_id, edge_mm, weight
    )
    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/check")
def check_warmup_step(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str = Form(),
    step_index: int = Form(ge=0, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    sets: int | None = Form(default=None, ge=1, le=MAX_SET_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand not in VALID_HANDS:
        return HTMLResponse("Hand must be left or right.", status_code=400)
    training_session = _start_play(
        session, user, grip_type_id, edge_mm, date, session_number, sets
    )
    training_log.toggle_warmup_check(session, training_session, hand, step_index)
    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/rung-done")
def rung_done(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str | None = Form(default=None),
    step_index: int = Form(ge=0, le=MAX_SET_NUMBER),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    sets: int | None = Form(default=None, ge=1, le=MAX_SET_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The play warmup step's primary button: ticks every in-play hand's
    tile for this rung (any already ticked by hand are left as-is) and
    advances to the next rung, or the first work set once every rung is
    done."""
    training_session = _start_play(
        session, user, grip_type_id, edge_mm, date, session_number, sets
    )
    hands = training_log.hands_for(user, hand)
    training_log.complete_warmup_rung(session, training_session, hands, step_index)
    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/rest/extend")
def extend_rest(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The "+30 s" rest action (orchestrator decision 1: bumps rest_ends_at
    by exactly 30 seconds)."""
    require_grip_type(session, grip_type_id)
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_log.extend_rest(training_session, session, seconds=30)
    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/rest/end")
def end_rest(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    hand: str | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Skip rest (while the ring is counting) and Start set N (once it's hit
    zero) are the same server action: clear rest_ends_at, moving the play
    step straight to the next work set."""
    require_grip_type(session, grip_type_id)
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_log.clear_rest(training_session, session)
    return play_response(
        request, user, session, grip_type_id, edge_mm, date, hand, session_number
    )


@router.post("/session/sets")
def plan_sets(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    sets: int = Form(ge=1, le=MAX_SET_NUMBER),
    hand: str | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The ⋯ menu's "＋ Add a set" / "－ Remove empty set" (PR #154 review,
    D2): persists the combo's planned set count on the session, so every
    later step and reload reads it rather than a URL hint."""
    try:
        training_log.set_planned_sets(
            session, user, grip_type_id, edge_mm, date, session_number, sets
        )
    except training_log.UnknownGripTypeError:
        raise HTTPException(status_code=404, detail="Unknown grip type") from None
    return play_response(
        request, user, session, grip_type_id, edge_mm, date,
        hand if hand in VALID_HANDS else None, session_number,
    )


def summary_redirect(
    grip_type_id: int | None,
    edge_mm: int | None,
    date: date_type,
    play_hand: str | None,
    session_number: int | None,
) -> RedirectResponse:
    """The no-JS answer for the summary step's autosave forms (#147): back
    to /session/play when the form carried its combo, else the timeline
    (#150; the pre-#147 /history fallback) every older caller of these
    endpoints still gets."""
    if grip_type_id is None or edge_mm is None:
        return RedirectResponse("/progress/timeline", status_code=303)
    hand = play_hand if play_hand in VALID_HANDS else None
    return play_redirect(grip_type_id, edge_mm, date, hand, session_number)


@router.post("/session/update")
def update_session(
    request: Request,
    date: date_type = Form(),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    notes: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
    is_deload: str | None = Form(default=None),
    grip_type_id: int | None = Form(default=None, ge=1, le=MAX_ROW_ID),
    edge_mm: int | None = Form(default=None, gt=0, le=MAX_EDGE_MM),
    hand: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Autosave endpoint for session-level fields. The form always posts
    both fields together, so a checkbox that's unchecked (and therefore
    omitted by the browser) is unambiguous: it means False.

    The optional combo fields (grip_type_id, edge_mm, hand) are only a
    return address: the summary step posts them so a no-JS save lands back
    on /session/play instead of the timeline."""
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_session.notes = notes or ""
        training_session.is_deload = (is_deload == "on")

        session.add(training_session)
        session.commit()

    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return summary_redirect(grip_type_id, edge_mm, date, hand, session_number)


@router.post("/session/rpe")
def save_session_rpe(
    request: Request,
    grip_type_id: int = Form(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    date: date_type = Form(),
    session_rpe: int = Form(ge=MIN_SESSION_RPE, le=MAX_SESSION_RPE),
    hand: str | None = Form(default=None),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Session RPE chip on the summary step (#147): autosaves on tap and
    answers like every play action -- the summary fragment for htmx, a 303
    back to /session/play for a plain form post. Scoped to the current
    user's own (date, session_number) session; there's nothing to rate
    before a set exists, so a missing session is a no-op, not a create."""
    require_grip_type(session, grip_type_id)
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_log.set_session_rpe(session, training_session, session_rpe)
    return play_response(
        request, user, session, grip_type_id, edge_mm, date,
        hand if hand in VALID_HANDS else None, session_number,
    )


@router.post("/session/finish")
def finish_session(
    request: Request,
    date: date_type = Form(),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Finish on the summary step (#147): stamps finished_at if it isn't
    set yet (idempotent) and goes home."""
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_log.finish_session(session, training_session)
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": "/"})
    return RedirectResponse("/", status_code=303)


@router.post("/session/pain-report")
def add_pain_report(
    request: Request,
    date: date_type = Form(),
    hand: str = Form(),
    severity: int = Form(ge=1, le=3),
    note: str | None = Form(default=None, max_length=MAX_NOTES_LENGTH),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    grip_type_id: int | None = Form(default=None, ge=1, le=MAX_ROW_ID),
    edge_mm: int | None = Form(default=None, gt=0, le=MAX_EDGE_MM),
    play_hand: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Tweaks (#147 summary step; formerly the "How did it feel?" card):
    at most one PainReport per (session, hand). The optional combo fields
    are only the no-JS return address -- `play_hand` rather than `hand`,
    since `hand` here is the tweaked hand, not the play page's hand."""
    if hand not in training_log.PAIN_REPORT_HANDS:
        return HTMLResponse("Hand must be left, right, or both.", status_code=400)
    training_session = training_log.find_session(session, user, date, session_number)
    if training_session is not None:
        training_log.record_pain_report(session, training_session, hand, severity, note)

    if request.headers.get("HX-Request"):
        return Response(status_code=204)
    return summary_redirect(grip_type_id, edge_mm, date, play_hand, session_number)


@router.get("/session/new")
def new_session_form(user: User = Depends(auth.current_user)):
    """Replaced by Today's plan + Change picker (#149)."""
    return RedirectResponse("/", status_code=303)


@router.get("/session/warmup")
def warmup_page(
    request: Request,
    grip_type_id: int = Query(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    session_number: int | None = Query(default=None, ge=1, le=MAX_SESSION_NUMBER),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Session play (#146, docs/adr/0014): /session/warmup is now just a
    redirect to /session/play, preserving every query parameter."""
    return play_redirect(grip_type_id, edge_mm, date, hand, session_number)


@router.get("/session/play")
def play_page(
    request: Request,
    grip_type_id: int = Query(ge=1, le=MAX_ROW_ID),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    date: date_type = Query(),
    hand: str | None = Query(default=None),
    session_number: int | None = Query(default=None, ge=1, le=MAX_SESSION_NUMBER),
    sets: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    edit: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    undo_set: int | None = Query(default=None, ge=1, le=MAX_SET_NUMBER),
    undo_left_weight: float | None = Query(default=None, gt=0, le=MAX_WEIGHT),
    undo_left_reps: int | None = Query(default=None, ge=1, le=MAX_REPS),
    undo_left_rpe: float | None = Query(default=None, ge=1, le=10),
    undo_right_weight: float | None = Query(default=None, gt=0, le=MAX_WEIGHT),
    undo_right_reps: int | None = Query(default=None, ge=1, le=MAX_REPS),
    undo_right_rpe: float | None = Query(default=None, ge=1, le=10),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The whole training session runs on this one page (#146,
    docs/adr/0014): the server derives which step (warmup rung, work set,
    rest, summary) to render purely from persisted state, so a reload — or
    Android killing the app — always lands back on the right step.

    The undo_* params (review item 2) are the no-JS carrier for the
    undo-after-delete banner: /session/set/delete's plain-form 303 redirect
    encodes the just-deleted set's values here so this GET can render the
    "Set N deleted [Undo]" affordance once, from the URL alone, with no
    server-side undo state to clean up afterwards."""
    require_grip_type(session, grip_type_id)
    if needs_creation_confirmation(session, user, date, session_number):
        return confirm_creation_response(
            request, user, "play", grip_type_id, edge_mm, date, hand,
            session_number,
        )
    undo: dict | None = None
    if undo_set is not None:
        undo_hands: dict[str, dict] = {}
        if undo_left_weight is not None and undo_left_reps is not None:
            undo_hands["left"] = {
                "weight": undo_left_weight, "reps": undo_left_reps, "rpe": undo_left_rpe,
            }
        if undo_right_weight is not None and undo_right_reps is not None:
            undo_hands["right"] = {
                "weight": undo_right_weight, "reps": undo_right_reps, "rpe": undo_right_rpe,
            }
        if undo_hands:
            undo = {"set_number": undo_set, "hands": undo_hands}
    view = training_log.play_view(
        session, user, grip_type_id, edge_mm, date, hand, session_number, sets, edit
    )
    return templates.TemplateResponse(
        request, "play.html", {"user": user, "hide_chrome": True, "undo": undo, **view}
    )
