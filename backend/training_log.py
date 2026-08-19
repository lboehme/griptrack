from datetime import date as date_type

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend import plates
from backend.limits import MAX_REPS, MAX_WEIGHT
from backend.models import (
    BodyWeightLog,
    GripType,
    MaxWeightTest,
    PainReport,
    SessionMaxEstimate,
    TrainingProtocol,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
)


class SetValidationError(ValueError):
    """Validation failure in a Set commit payload."""


ValidationError = SetValidationError


class UnknownGripTypeError(ValueError):
    """Grip type not found."""


UnknownGripType = UnknownGripTypeError


def require_grip_type(session: Session, grip_type_id: int) -> GripType:
    grip = session.get(GripType, grip_type_id)
    if grip is None:
        raise UnknownGripTypeError(f"Unknown grip type id: {grip_type_id}")
    return grip


def bodyweight_at(
    session: Session, user: User, as_of: date_type | None = None
) -> BodyWeightLog | None:
    """The user's bodyweight entry closest at-or-before a date (see
    CONTEXT.md: BodyWeightLog); as_of=None means the current bodyweight."""
    query = (
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == user.id)
        .order_by(BodyWeightLog.date.desc(), BodyWeightLog.id.desc())
    )
    if as_of is not None:
        query = query.where(BodyWeightLog.date <= as_of)
    return session.exec(query).first()


def hands_for(user: User, hand: str | None) -> list[str]:
    """HandOrderPreference policy: "alternating" shows both hands side by
    side; "sequential" does one hand's full flow at a time (default left,
    an explicit hand selects the other)."""
    if user.hand_order_pref == "sequential":
        return [hand if hand in ("left", "right") else "left"]
    return ["left", "right"]


def warmup_view(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None = None,
    session_number: int | None = None,
) -> dict:
    """Everything the warmup page shows, assembled in one call. Each hand's
    ramp is sourced independently: CurrentMax, else this session's
    SessionMaxEstimate, else the hand lands in untested_hands and gets an
    inline estimate-entry form.

    session_number=None resolves to the day's latest session (see
    find_session) — the default flow every page uses unless the user
    explicitly started a second session today."""
    hands = hands_for(user, hand)
    training_session = find_session(session, user, date, session_number)
    plans = {
        h: compute_ramp_plan(
            session, user, h, grip_type_id, edge_mm, training_session
        )
        for h in hands
    }
    untested_hands = [h for h, plan in plans.items() if plan is None]
    planned_hands = [h for h in hands if plans[h] is not None]
    steps = []
    if planned_hands:
        first_plan = plans[planned_hands[0]]
        # planned_hands is exactly the hands whose plan isn't None.
        assert first_plan is not None
        steps = [
            {"index": index, "percent": first_plan[index]["percent"]}
            for index in range(len(first_plan))
        ]
    checks = warmup_checks(session, training_session)
    # Card-ladder progress pill (issue #83): the 1-based number of the
    # first step that isn't yet fully ticked across every planned hand, or
    # the last step once everything is checked. Display-only — the ramp
    # itself has no enforced order, this is just "how far down the plan
    # have you ticked".
    current_step = len(steps)
    for step in steps:
        if not all((h, step["index"]) in checks for h in planned_hands):
            current_step = step["index"] + 1
            break
    return {
        "grip": session.get(GripType, grip_type_id),
        "edge_mm": edge_mm,
        "date": date,
        "session_number": resolve_session_number(
            session, user, date, session_number, training_session
        ),
        "hands": hands,
        "plans": plans,
        "untested_hands": untested_hands,
        "planned_hands": planned_hands,
        "steps": steps,
        "current_step": current_step,
        "training_session": training_session,
        "checks": checks,
    }


def _current_set_number(hands: list[str], saved: dict, row_count: int) -> int:
    """The Set commit's target set_number — the lowest set_number that
    isn't yet fully logged for every hand in play. Once every row up to
    row_count is complete, this is row_count + 1 (the "extend with ＋ Add a
    set" state)."""
    for n in range(1, row_count + 1):
        if any((h, n) not in saved for h in hands):
            return n
    return row_count + 1


def _seed_for_hand(
    hand: str,
    current_set_number: int,
    saved: dict,
    current_max: dict,
    default_reps: int,
) -> dict:
    """The Focus screen's in-progress values for one hand.

    If this hand already has a saved WorkSet for the current set_number
    (e.g. only one hand of an alternating pair has committed so far, so
    the set isn't "complete" yet and current_set_number hasn't advanced),
    that row's own values win, RPE included — reloading the page must not
    forget what was just saved. Otherwise this is a genuinely new set:
    weight/reps and RPE carry down from the most recently committed set for
    this hand, else the usual CurrentMax/default-reps prefill and RPE starts
    blank (nullable) if there is no prior set or the prior set had no RPE."""
    existing = saved.get((hand, current_set_number))
    if existing is not None:
        return {"weight": existing.weight, "reps": existing.reps, "rpe": existing.rpe}
    for n in range(current_set_number - 1, 0, -1):
        prior = saved.get((hand, n))
        if prior is not None:
            return {"weight": prior.weight, "reps": prior.reps, "rpe": prior.rpe}
    return {"weight": current_max.get(hand), "reps": default_reps, "rpe": None}


def worksets_view(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None = None,
    sets_hint: int | None = None,
    session_number: int | None = None,
    edit_set: int | None = None,
) -> dict:
    """Everything the work-sets (Focus) page shows: saved sets by
    (hand, set), prefills from CurrentMax and the TrainingProtocol, the row
    math (default rows, add-another-set hint, dismissable empty rows), the
    current in-progress set + its per-hand seed values, and the user's
    loadable ladder (see CONTEXT.md: Loadable ladder) for the weight
    steppers.

    session_number=None resolves to the day's latest session, same as
    warmup_view.

    edit_set is the Focus screen's Edit mode (issue #80): tapping a
    COMPLETED row re-requests this same view with edit_set=that set_number.
    "current_set_number" always stays the normal in-progress pointer (the
    lowest not-yet-fully-logged set) -- it never shifts to the set being
    edited -- because it doubles as the "set the user was on" to return to
    once Save/Cancel finishes. `display_set_number`/`seed` are what the
    form actually renders (the edit target's saved values while editing),
    while `resume_seed` and `saved_json` are handed to the client so it can
    enter/exit edit mode for any COMPLETED row without a round trip."""
    hands = hands_for(user, hand)
    protocol = get_protocol(session, user)
    training_session = find_session(session, user, date, session_number)
    saved = {
        (ws.hand, ws.set_number): ws
        for ws in worksets_for_combo(
            session, user, grip_type_id, edge_mm, date, session_number
        )
    }
    current_max = {
        h: effective_max(session, user, h, grip_type_id, edge_mm, training_session)
        for h in hands
    }
    highest_saved = max((n for _, n in saved), default=0)
    needed_rows = max(protocol.default_work_sets, highest_saved)
    row_count = max(needed_rows, sets_hint or 0)
    current_set_number = _current_set_number(hands, saved, row_count)
    resume_seed = {
        h: _seed_for_hand(
            h, current_set_number, saved, current_max, protocol.base_work_set_reps
        )
        for h in hands
    }
    # A completed row is only ever rendered for a fully-logged set, so
    # editing = True whenever *any* in-play hand has a saved row for
    # edit_set; an out-of-range/bogus edit= param just falls back to the
    # normal in-progress view instead of erroring.
    editing = edit_set is not None and any((h, edit_set) in saved for h in hands)
    display_set_number = edit_set if editing else current_set_number
    if editing:
        assert edit_set is not None  # implied by `editing`; narrows for mypy
        seed = {
            h: (
                {
                    "weight": saved[(h, edit_set)].weight,
                    "reps": saved[(h, edit_set)].reps,
                    "rpe": saved[(h, edit_set)].rpe,
                }
                if (h, edit_set) in saved
                else resume_seed[h]
            )
            for h in hands
        }
    else:
        seed = resume_seed
    saved_json: dict[int, dict[str, dict]] = {}
    for (h, n), ws in saved.items():
        saved_json.setdefault(n, {})[h] = {
            "weight": ws.weight, "reps": ws.reps, "rpe": ws.rpe,
        }
    inventory = plates.inventory_for(session, user)
    return {
        "grip": session.get(GripType, grip_type_id),
        "edge_mm": edge_mm,
        "date": date,
        "session_number": resolve_session_number(
            session, user, date, session_number, training_session
        ),
        "hands": hands,
        "set_numbers": list(range(1, row_count + 1)),
        "saved": saved,
        "current_max": current_max,
        "default_reps": protocol.base_work_set_reps,
        "more_sets": row_count + 1,
        # Extra empty rows (from "add another set") can be dismissed again.
        "removable_to": row_count - 1 if row_count > needed_rows else None,
        "training_session": training_session,
        "pain_reports": session.exec(
            select(PainReport).where(PainReport.training_session_id == training_session.id)
        ).all() if training_session else [],
        "total_sets": row_count,
        "current_set_number": current_set_number,
        "pill_set_number": min(current_set_number, row_count),
        "seed": seed,
        "ladder": plates.loadable_ladder(inventory),
        "editing": editing,
        "display_set_number": display_set_number,
        "resume_seed": resume_seed,
        "saved_json": saved_json,
    }


def delete_work_set(
    session: Session,
    training_session: TrainingSession,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    set_number: int,
) -> bool:
    work_set = session.exec(
        select(WorkSet)
        .where(WorkSet.training_session_id == training_session.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(WorkSet.set_number == set_number)
    ).first()
    if work_set is None:
        return False
    session.delete(work_set)
    session.commit()
    return True


def delete_set_and_renumber(
    session: Session,
    training_session: TrainingSession,
    grip_type_id: int,
    edge_mm: int,
    set_number: int,
    commit: bool = True,
) -> dict[str, dict]:
    """Delete all in-play hands' WorkSets for the given set_number and
    renumber any higher sets down by 1 in a single transaction, keeping the
    1..N sequence contiguous with no gaps. Returns the deleted hands' data."""
    deleted_rows = session.exec(
        select(WorkSet)
        .where(WorkSet.training_session_id == training_session.id)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(WorkSet.set_number == set_number)
    ).all()

    if not deleted_rows:
        return {}

    deleted_data = {
        ws.hand: {"weight": ws.weight, "reps": ws.reps, "rpe": ws.rpe}
        for ws in deleted_rows
    }

    for ws in deleted_rows:
        session.delete(ws)

    # Shift higher sets down by 1
    higher_rows = session.exec(
        select(WorkSet)
        .where(WorkSet.training_session_id == training_session.id)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(WorkSet.set_number > set_number)
        .order_by(WorkSet.set_number.asc())
    ).all()

    for ws in higher_rows:
        ws.set_number -= 1
        session.add(ws)

    if commit:
        session.commit()

    return deleted_data


def restore_set_at(
    session: Session,
    training_session: TrainingSession,
    grip_type_id: int,
    edge_mm: int,
    set_number: int,
    hands_payload: dict[str, tuple[float, int, float | None]],
    commit: bool = True,
) -> None:
    """Insert a set at set_number, shifting any existing sets at or above
    set_number up by 1, and write the restored hands' data."""
    higher_rows = session.exec(
        select(WorkSet)
        .where(WorkSet.training_session_id == training_session.id)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(WorkSet.set_number >= set_number)
        .order_by(WorkSet.set_number.desc())
    ).all()

    for ws in higher_rows:
        ws.set_number += 1
        session.add(ws)

    for hand, (weight, reps, rpe) in hands_payload.items():
        ws = WorkSet(
            training_session_id=training_session.id,
            hand=hand,
            grip_type_id=grip_type_id,
            edge_mm=edge_mm,
            set_number=set_number,
            weight=weight,
            reps=reps,
            rpe=rpe,
        )
        session.add(ws)

    if commit:
        session.commit()


def parse_hands_payload(
    left_weight: float | None = None,
    left_reps: int | None = None,
    left_rpe: float | None = None,
    right_weight: float | None = None,
    right_reps: int | None = None,
    right_rpe: float | None = None,
) -> dict[str, tuple[float, int, float | None]]:
    """Validate the per-hand Set-commit payload shared by Set commit and restore:
    every present hand gets the same bounds and RPE grid as /session/workset,
    *before* anything touches the DB, so an invalid or partial payload writes
    nothing. A hand with all three fields None wasn't submitted (sequential
    hand order) and is skipped. Raises SetValidationError on the first
    validation failure. Returns the validated `{hand: (weight, reps, rpe)}` dict.
    """
    raw = {
        "left": (left_weight, left_reps, left_rpe),
        "right": (right_weight, right_reps, right_rpe),
    }
    hands_payload: dict[str, tuple[float, int, float | None]] = {}
    for hand, (weight, reps, rpe) in raw.items():
        if weight is None and reps is None and rpe is None:
            continue  # this hand wasn't submitted (sequential hand order)
        if weight is None or reps is None:
            raise SetValidationError(f"{hand} hand needs both weight and reps.")
        if not (0 < weight <= MAX_WEIGHT):
            raise SetValidationError("Weight out of range.")
        if not (1 <= reps <= MAX_REPS):
            raise SetValidationError("Reps out of range.")
        if rpe is not None and not (1.0 <= rpe <= 10.0 and (rpe * 2) == int(rpe * 2)):
            raise SetValidationError("RPE must be between 1 and 10 in 0.5 steps.")
        hands_payload[hand] = (weight, reps, rpe)

    if not hands_payload:
        raise SetValidationError("At least one hand's weight and reps are required.")
    return hands_payload


def commit_focus_set(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    set_number: int,
    session_number: int | None,
    hands_payload: dict[str, tuple[float, int, float | None]],
) -> TrainingSession:
    """Set commit (docs/adr/0007-set-commit-over-per-cell-autosave.md):
    writes both hands' WorkSets for one set_number in a single atomic
    transaction. Validates grip type, finds/starts session, stages both hands
    with record_work_set(commit=False), commits atomically, and returns the
    training session."""
    require_grip_type(session, grip_type_id)
    training_session = start_or_get_session(session, user, date, session_number)
    for hand, (weight, reps, rpe) in hands_payload.items():
        record_work_set(
            session,
            training_session,
            hand,
            grip_type_id,
            edge_mm,
            set_number,
            weight,
            reps,
            rpe,
            commit=False,
        )
    session.commit()
    return training_session


def restore_focus_set(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    set_number: int,
    session_number: int | None,
    hands_payload: dict[str, tuple[float, int, float | None]],
) -> TrainingSession:
    """Undo counterpart to delete_set_and_renumber: validates grip type,
    starts or gets the session, re-inserts the deleted set at its original
    set_number (shifting higher sets back up) with the supplied values in one
    transaction, and returns the training session."""
    require_grip_type(session, grip_type_id)
    training_session = start_or_get_session(session, user, date, session_number)
    restore_set_at(
        session,
        training_session,
        grip_type_id,
        edge_mm,
        set_number,
        hands_payload,
        commit=True,
    )
    return training_session


def worksets_for_combo(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    session_number: int | None = None,
) -> list[WorkSet]:
    training_session = find_session(session, user, date, session_number)
    if training_session is None:
        return []
    return list(
        session.exec(
            select(WorkSet)
            .where(WorkSet.training_session_id == training_session.id)
            .where(WorkSet.grip_type_id == grip_type_id)
            .where(WorkSet.edge_mm == edge_mm)
        )
    )


def record_work_set(
    session: Session,
    training_session: TrainingSession,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    set_number: int,
    weight: float,
    reps: int,
    rpe: float | None,
    commit: bool = True,
) -> WorkSet:
    """Upsert one work set — every field edit autosaves, so the same
    (hand, set_number) cell is written repeatedly within a session.

    commit=False stages the row (session.add only) without committing or
    refreshing, so a caller can upsert both hands of a Set commit
    (see docs/adr/0007) and commit them together as one transaction — the
    per-hand /session/workset primitive still calls this with the default
    commit=True."""
    work_set = session.exec(
        select(WorkSet)
        .where(WorkSet.training_session_id == training_session.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(WorkSet.set_number == set_number)
    ).first()
    if work_set is None:
        work_set = WorkSet(
            training_session_id=training_session.id,
            hand=hand,
            grip_type_id=grip_type_id,
            edge_mm=edge_mm,
            set_number=set_number,
            weight=weight,
            reps=reps,
            rpe=rpe,
        )
    else:
        work_set.weight = weight
        work_set.reps = reps
        work_set.rpe = rpe
    session.add(work_set)
    if commit:
        session.commit()
        session.refresh(work_set)
    return work_set


def start_or_get_session(
    session: Session,
    user: User,
    date: date_type,
    session_number: int | None = None,
) -> TrainingSession:
    """The TrainingSession for this user+date(+session_number), created on
    first use — a session exists from the first checkbox tap, there is no
    submit step.

    session_number=None (the default flow) means "the day's latest
    session" — create session_number 1 if none exists yet for that date,
    otherwise reuse the highest-numbered one. An explicit session_number
    (the "start a second session today" affordance) gets or creates that
    exact slot instead.

    Two concurrent first-POSTs on the same (user, date) can both read "no
    session yet" and both compute the same next_number — the loser then
    hits the (user_id, date, session_number) unique constraint on commit.
    This also matters for offline-sync replay (#20), where a queued write
    can land after a session on the same date was created elsewhere in the
    meantime. Rather than surface a 500, retry once: the winner's row is
    now committed, so a plain re-fetch finds it."""
    training_session = find_session(session, user, date, session_number)
    if training_session is not None:
        return training_session
    next_number = session_number if session_number is not None else (
        (latest_session_number(session, user, date) or 0) + 1
    )
    training_session = TrainingSession(
        user_id=user.id, date=date, session_number=next_number
    )
    session.add(training_session)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        training_session = find_session(session, user, date, next_number)
        if training_session is None:
            raise
        return training_session
    session.refresh(training_session)
    return training_session


def find_session(
    session: Session,
    user: User,
    date: date_type,
    session_number: int | None = None,
) -> TrainingSession | None:
    """The session for this user+date. With session_number=None (the
    default flow), resolves to the day's latest session."""
    query = (
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date == date)
    )
    if session_number is not None:
        query = query.where(TrainingSession.session_number == session_number)
    else:
        query = query.order_by(TrainingSession.session_number.desc())
    return session.exec(query).first()


def latest_session_number(
    session: Session, user: User, date: date_type
) -> int | None:
    """The highest session_number logged on this date, or None if the user
    has no session on that date yet — what the "start a second session
    today" affordance and start_or_get_session's auto-numbering key off."""
    existing = find_session(session, user, date)
    return existing.session_number if existing is not None else None


def resolve_session_number(
    session: Session,
    user: User,
    date: date_type,
    session_number: int | None,
    training_session: TrainingSession | None,
) -> int:
    """The concrete session_number a session page should pin into its
    hidden field, so every autosave POST targets one specific slot instead
    of re-resolving "the day's latest session" at POST time — two tabs
    open on today before any session exists could otherwise land their
    edits in different sessions. Mirrors start_or_get_session's own
    next-number arithmetic, so the pinned value always matches what that
    call would create."""
    if training_session is not None:
        return training_session.session_number
    if session_number is not None:
        return session_number
    return (latest_session_number(session, user, date) or 0) + 1


def is_past_date(date: date_type, today: date_type | None = None) -> bool:
    """Whether `date` is strictly before today — the server-side heuristic
    that gates *creating* a session (see CLAUDE.md: explicit past-session
    creation). The client-local "today" used for the on-page warning
    banner is a separate, JS-side comparison; this one only needs to be
    right to the day, not the client's timezone."""
    return date < (today if today is not None else date_type.today())


def toggle_warmup_check(
    session: Session, training_session: TrainingSession, hand: str, step_index: int
) -> None:
    """Check the step, or uncheck it when already checked (accidental tap)."""
    exists = session.exec(
        select(WarmupStepCheck)
        .where(WarmupStepCheck.training_session_id == training_session.id)
        .where(WarmupStepCheck.hand == hand)
        .where(WarmupStepCheck.step_index == step_index)
    ).first()
    if exists is None:
        session.add(
            WarmupStepCheck(
                training_session_id=training_session.id,
                hand=hand,
                step_index=step_index,
            )
        )
    else:
        session.delete(exists)
    session.commit()


def warmup_checks(
    session: Session, training_session: TrainingSession | None
) -> set[tuple[str, int]]:
    if training_session is None:
        return set()
    return {
        (check.hand, check.step_index)
        for check in session.exec(
            select(WarmupStepCheck).where(
                WarmupStepCheck.training_session_id == training_session.id
            )
        )
    }


def get_protocol(session: Session, user: User) -> TrainingProtocol:
    """The user's TrainingProtocol, falling back to the global default row."""
    protocol = session.exec(
        select(TrainingProtocol).where(TrainingProtocol.user_id == user.id)
    ).first()
    if protocol is None:
        protocol = session.exec(
            select(TrainingProtocol).where(TrainingProtocol.user_id == None)  # noqa: E711
        ).one()
    return protocol


def compute_ramp_plan(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    training_session: TrainingSession | None = None,
) -> list[dict] | None:
    """Plate-rounded warmup/ramp steps for one hand, or None if untested.

    With a training_session, an untested hand falls back to that session's
    SessionMaxEstimate — CurrentMax itself is never affected."""
    current_max = effective_max(
        session, user, hand, grip_type_id, edge_mm, training_session
    )
    if current_max is None:
        return None
    protocol = get_protocol(session, user)
    inventory = plates.inventory_for(session, user)
    return [
        {
            "percent": percent,
            "target": current_max * percent / 100,
            "weight": plates.round_down_to_loadable(
                current_max * percent / 100, inventory
            ),
        }
        for percent in (int(p) for p in protocol.ramp_percentages.split(","))
    ]


def effective_max(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    training_session: TrainingSession | None,
) -> float | None:
    """The max the warmup ramp and work-set prefills work from: CurrentMax,
    else this session's SessionMaxEstimate, else None. Analytics never use
    this — they read compute_current_max directly."""
    current_max = compute_current_max(session, user, hand, grip_type_id, edge_mm)
    if current_max is not None:
        return current_max
    if training_session is None:
        return None
    estimate = session_estimate(
        session, training_session, hand, grip_type_id, edge_mm
    )
    return estimate.weight if estimate is not None else None


def session_estimate(
    session: Session,
    training_session: TrainingSession,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
) -> SessionMaxEstimate | None:
    return session.exec(
        select(SessionMaxEstimate)
        .where(SessionMaxEstimate.training_session_id == training_session.id)
        .where(SessionMaxEstimate.hand == hand)
        .where(SessionMaxEstimate.grip_type_id == grip_type_id)
        .where(SessionMaxEstimate.edge_mm == edge_mm)
    ).first()


def record_session_estimate(
    session: Session,
    training_session: TrainingSession,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    weight: float,
) -> SessionMaxEstimate:
    """Upsert this session's estimate for one (hand, grip, edge) — like every
    session-page interaction, resubmission overwrites in place."""
    estimate = session_estimate(
        session, training_session, hand, grip_type_id, edge_mm
    )
    if estimate is None:
        estimate = SessionMaxEstimate(
            training_session_id=training_session.id,
            hand=hand,
            grip_type_id=grip_type_id,
            edge_mm=edge_mm,
            weight=weight,
        )
    else:
        estimate.weight = weight
    session.add(estimate)
    session.commit()
    session.refresh(estimate)
    return estimate


def latest_max_test(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
) -> MaxWeightTest | None:
    query = (
        select(MaxWeightTest)
        .where(MaxWeightTest.user_id == user.id)
        .where(MaxWeightTest.voided_at.is_(None))
        .where(MaxWeightTest.hand == hand)
        .where(MaxWeightTest.grip_type_id == grip_type_id)
        .where(MaxWeightTest.edge_mm == edge_mm)
        .order_by(MaxWeightTest.date.desc(), MaxWeightTest.id.desc())
    )
    if as_of is not None:
        query = query.where(MaxWeightTest.date <= as_of)
    return session.exec(query).first()


def compute_current_max(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
) -> float | None:
    """CurrentMax: the heavier of the latest MaxWeightTest and the heaviest
    WorkSet logged since that test (see CONTEXT.md: CurrentMax).

    A newer test supersedes everything before it, even when lower
    (deliberate reset) — work sets predating the latest test never count.
    With `as_of`, the same rule evaluated as of that date (the single
    implementation the correlation analysis uses too). Returns None when
    the combination has never been tested.
    """
    test = latest_max_test(session, user, hand, grip_type_id, edge_mm, as_of)
    if test is None:
        return None
    workset_query = (
        select(WorkSet)
        .join(TrainingSession, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date >= test.date)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .order_by(WorkSet.weight.desc())
    )
    if as_of is not None:
        workset_query = workset_query.where(TrainingSession.date <= as_of)
    heaviest_since = session.exec(workset_query).first()
    if heaviest_since is not None and heaviest_since.weight > test.weight:
        return heaviest_since.weight
    return test.weight


def record_max_weight_test(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    date,
    weight: float,
) -> MaxWeightTest:
    test = MaxWeightTest(
        user_id=user.id,
        hand=hand,
        grip_type_id=grip_type_id,
        edge_mm=edge_mm,
        date=date,
        weight=weight,
    )
    session.add(test)
    session.commit()
    session.refresh(test)
    return test


def last_used_combination(session: Session, user: User) -> tuple[int, int] | None:
    """(grip_type_id, edge_mm) the user last trained or tested with.

    Actual training (the latest WorkSet by session date) outranks the
    latest MaxWeightTest: tests are rare, training is the living signal.
    """
    work_set = session.exec(
        select(WorkSet)
        .join(TrainingSession, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .order_by(TrainingSession.date.desc(), WorkSet.id.desc())
    ).first()
    test = session.exec(
        select(MaxWeightTest)
        .where(MaxWeightTest.user_id == user.id)
        .where(MaxWeightTest.voided_at.is_(None))
        .order_by(MaxWeightTest.date.desc(), MaxWeightTest.id.desc())
    ).first()

    latest_signals = []
    if work_set is not None:
        work_session = session.get(TrainingSession, work_set.training_session_id)
        latest_signals.append((work_session.date, 1, work_set.grip_type_id, work_set.edge_mm))
    if test is not None:
        latest_signals.append((test.date, 0, test.grip_type_id, test.edge_mm))
    if not latest_signals:
        return None
    _, _, grip_type_id, edge_mm = max(latest_signals)
    return (grip_type_id, edge_mm)


def session_history(session: Session, user: User) -> list[dict]:
    """Past TrainingSessions (newest first, latest session_number first
    within a date), each with its WorkSets."""
    sessions = session.exec(
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
        .order_by(
            TrainingSession.date.desc(),
            TrainingSession.session_number.desc(),
            TrainingSession.id.desc(),
        )
    ).all()
    history = []
    for training_session in sessions:
        work_sets = session.exec(
            select(WorkSet)
            .where(WorkSet.training_session_id == training_session.id)
            .order_by(WorkSet.set_number, WorkSet.hand)  # type: ignore[arg-type]  # SQLModel columns typed as int/str, not Column
        ).all()
        history.append({"session": training_session, "work_sets": work_sets})
    return history


def grip_names(session: Session) -> dict[int, str]:
    """GripType id -> display name, for anything rendering WorkSets."""
    # grip.id is None only for a transient, unpersisted GripType; every row
    # returned by a query has already been assigned a primary key.
    return {grip.id: grip.name for grip in session.exec(select(GripType))}  # type: ignore[misc]


def grip_dimension_names(session: Session) -> dict[int, str]:
    """GripType id -> dimension_name ("edge depth" / "block width"), for
    anything rendering a WorkSet's edge_mm value next to its grip — see
    CONTEXT.md on pinch dimension semantics."""
    return {grip.id: grip.dimension_name for grip in session.exec(select(GripType))}  # type: ignore[misc]


def trained_combinations(session: Session, user: User) -> list[dict]:
    """One entry per (hand, grip_type, edge_mm) with any WorkSet or
    MaxWeightTest — what the dashboard iterates. A combo trained only under
    a SessionMaxEstimate appears too; its current_max is simply None."""
    tests = session.exec(
        select(MaxWeightTest).where(MaxWeightTest.user_id == user.id).where(MaxWeightTest.voided_at.is_(None))
    ).all()
    work_sets = session.exec(
        select(WorkSet)
        .join(TrainingSession, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
    ).all()
    combos = sorted(
        {(t.hand, t.grip_type_id, t.edge_mm) for t in tests}
        | {(ws.hand, ws.grip_type_id, ws.edge_mm) for ws in work_sets}
    )
    names = grip_names(session)
    dimension_names = grip_dimension_names(session)
    return [
        {
            "hand": hand,
            "grip_type_id": grip_type_id,
            "grip_name": names[grip_type_id],
            "dimension_name": dimension_names[grip_type_id],
            "edge_mm": edge_mm,
            "current_max": compute_current_max(
                session, user, hand, grip_type_id, edge_mm
            ),
        }
        for hand, grip_type_id, edge_mm in combos
    ]


def tested_combinations(session: Session, user: User) -> list[dict]:
    """One entry per tested (hand, grip_type, edge_mm), with its CurrentMax
    and the grip's display name — callers never join names themselves."""
    tests = session.exec(
        select(MaxWeightTest).where(MaxWeightTest.user_id == user.id).where(MaxWeightTest.voided_at.is_(None))
    ).all()
    combos = sorted({(t.hand, t.grip_type_id, t.edge_mm) for t in tests})
    names = grip_names(session)
    dimension_names = grip_dimension_names(session)
    return [
        {
            "hand": hand,
            "grip_type_id": grip_type_id,
            "grip_name": names[grip_type_id],
            "dimension_name": dimension_names[grip_type_id],
            "edge_mm": edge_mm,
            "current_max": compute_current_max(
                session, user, hand, grip_type_id, edge_mm
            ),
        }
        for hand, grip_type_id, edge_mm in combos
    ]
