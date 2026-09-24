from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend import plates
from backend.limits import (
    MAX_REPS,
    MAX_REST_EXTENSION_SECONDS,
    MAX_REST_SECONDS,
    MAX_WEIGHT,
)
from backend.models import (
    BodyWeightLog,
    GripType,
    MaxWeightTest,
    PainReport,
    ProgressionSettings,
    SessionMaxEstimate,
    TrainingProtocol,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
    utcnow,
)


class SetValidationError(ValueError):
    """Validation failure in a Set commit payload."""


class UnknownGripTypeError(ValueError):
    """Grip type not found."""


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
    # Function-local: analytics imports training_log, so a module-level
    # import here would be circular.
    from backend import analytics

    nudge = analytics.session_start_nudge(
        session, user, grip_type_id, edge_mm, date, hands
    )
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
        "nudge": nudge,
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
    plan_seed: dict,
) -> dict:
    """The Focus screen's in-progress values for one hand.

    If this hand already has a saved WorkSet for the current set_number
    (e.g. only one hand of an alternating pair has committed so far, so
    the set isn't "complete" yet and current_set_number hasn't advanced),
    that row's own values win, RPE included — reloading the page must not
    forget what was just saved. Otherwise this is a genuinely new set:
    weight/reps and RPE carry down from the most recently committed set for
    this hand, else -- set 1 of the session for this hand -- exactly
    Today's plan (backend.plan.combo_plan: suggestion, last session's top
    weight or CurrentMax, Go lighter's 85% included; PR #154 review D1),
    and RPE starts blank (nullable) if there is no prior set or the prior
    set had no RPE."""
    existing = saved.get((hand, current_set_number))
    if existing is not None:
        return {"weight": existing.weight, "reps": existing.reps, "rpe": existing.rpe}
    for n in range(current_set_number - 1, 0, -1):
        prior = saved.get((hand, n))
        if prior is not None:
            return {"weight": prior.weight, "reps": prior.reps, "rpe": prior.rpe}
    return {"weight": plan_seed["weight"], "reps": plan_seed["reps"], "rpe": None}


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
    persisted = persisted_planned_sets(training_session, grip_type_id, edge_mm)
    # A `sets=` URL hint (Today's "+1 set") is only a one-time initialiser:
    # once the session has a planned count for this combo it's ignored,
    # and until then every play form carries it (`sets_init`) so the first
    # POST on the combo persists it (PR #154 review, D2).
    sets_init = sets_hint if persisted is None else None
    row_count = max(needed_rows, persisted or sets_init or 0)
    current_set_number = _current_set_number(hands, saved, row_count)
    # Function-local: plan (and analytics) import training_log, so a
    # module-level import here would be circular.
    from backend import plan as plan_module

    combo_plan = plan_module.combo_plan(
        session, user, date, grip_type_id, edge_mm, training_session, session_number
    )
    resume_seed = {
        h: _seed_for_hand(
            h, current_set_number, saved,
            {"weight": combo_plan.hand(h).weight, "reps": combo_plan.reps},
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
    # The hand cards the form renders. Edit mode edits a saved set, so only
    # the hands that logged it (PR #154 review MUST-FIX 5: after a
    # sequential -> alternating switch, the other hand may have no row --
    # and no max -- for that set, and must not render an empty card).
    card_hands = (
        [h for h in hands if (h, edit_set) in saved] if editing else list(hands)
    )
    saved_json: dict[int, dict[str, dict]] = {}
    for (h, n), ws in saved.items():
        saved_json.setdefault(n, {})[h] = {
            "weight": ws.weight, "reps": ws.reps, "rpe": ws.rpe,
        }
    inventory = plates.inventory_for(session, user)
    # Function-local: analytics imports training_log, so a module-level
    # import here would be circular.
    from backend import analytics

    nudge = analytics.session_start_nudge(
        session, user, grip_type_id, edge_mm, date, hands
    )
    # The plan already evaluated the autoregulation suggestions for both
    # hands with this same session context.
    autoreg_suggestions = {h: combo_plan.suggestions.get(h) for h in hands}
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
        "default_rest_seconds": protocol.default_rest_seconds,
        "more_sets": row_count + 1,
        "sets_init": sets_init,
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
        "card_hands": card_hands,
        "display_set_number": display_set_number,
        "resume_seed": resume_seed,
        "saved_json": saved_json,
        "nudge": nudge,
        "autoreg_suggestions": autoreg_suggestions,
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
    1..N sequence contiguous with no gaps. Returns the deleted hands' data.

    Session play (#146): also clears any pending rest_ends_at -- deleting a
    set invalidates whatever "rest before set N" plan was in flight, and
    the play step must land back on the work-set step (with its undo
    banner) rather than a stale rest countdown."""
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

    if training_session.rest_ends_at is not None:
        training_session.rest_ends_at = None
        session.add(training_session)

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


def planned_set_count(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    session_number: int | None,
    sets_hint: int | None,
) -> int:
    """The row_count (denominator) worksets_view/play_view render: at least
    TrainingProtocol.default_work_sets, extended by whichever is bigger of
    the highest already-saved set_number or the session's persisted
    planned_sets for this combo (else the one-time `sets` initialiser)."""
    protocol = get_protocol(session, user)
    saved_numbers = {
        ws.set_number
        for ws in worksets_for_combo(
            session, user, grip_type_id, edge_mm, date, session_number
        )
    }
    highest_saved = max(saved_numbers, default=0)
    needed_rows = max(protocol.default_work_sets, highest_saved)
    persisted = persisted_planned_sets(
        find_session(session, user, date, session_number), grip_type_id, edge_mm
    )
    return max(needed_rows, persisted or sets_hint or 0)


def is_play_combo(
    training_session: TrainingSession, grip_type_id: int, edge_mm: int
) -> bool:
    """Whether (grip, edge) is the combo play is running in this session.
    An unstamped session (legacy rows, sets saved through the old per-hand
    endpoint) matches every combo, as before the stamp existed."""
    if training_session.play_grip_type_id is None:
        return True
    return (
        training_session.play_grip_type_id == grip_type_id
        and training_session.play_edge_mm == edge_mm
    )


def persisted_planned_sets(
    training_session: TrainingSession | None, grip_type_id: int, edge_mm: int
) -> int | None:
    """The session's planned set count, if it belongs to this combo."""
    if training_session is None or training_session.play_grip_type_id is None:
        return None
    if not is_play_combo(training_session, grip_type_id, edge_mm):
        return None
    return training_session.planned_sets


def stamp_play_combo(
    session: Session,
    training_session: TrainingSession,
    grip_type_id: int,
    edge_mm: int,
    sets_init: int | None = None,
    commit: bool = True,
) -> None:
    """Record that play has actually started on this combo (a rung-done, a
    warmup tick, an estimate or a Set commit -- never a GET), so Today's
    Resume reopens it (PR #154 review, D2). Moving to a different combo
    starts that combo's own plan: its planned count is the page's one-time
    `sets` initialiser (or the default), and a pending rest -- which
    belonged to the previous combo -- is dropped."""
    same = (
        training_session.play_grip_type_id == grip_type_id
        and training_session.play_edge_mm == edge_mm
    )
    if not same:
        training_session.play_grip_type_id = grip_type_id
        training_session.play_edge_mm = edge_mm
        training_session.planned_sets = sets_init
        training_session.rest_ends_at = None
    elif training_session.planned_sets is None and sets_init is not None:
        training_session.planned_sets = sets_init
    session.add(training_session)
    if commit:
        session.commit()
        session.refresh(training_session)


def start_play_on_combo(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    session_number: int | None,
    sets_init: int | None = None,
) -> TrainingSession:
    """The session a play action on this combo writes to (created on first
    use, like every session-page interaction), stamped as the combo play
    is running. Raises UnknownGripTypeError for an unknown grip -- an
    orphan grip id would otherwise break re-import of the user's export."""
    require_grip_type(session, grip_type_id)
    training_session = start_or_get_session(session, user, date, session_number)
    stamp_play_combo(session, training_session, grip_type_id, edge_mm, sets_init)
    return training_session


def set_planned_sets(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    session_number: int | None,
    sets: int,
) -> TrainingSession:
    """The ⋯ menu's "＋ Add a set" / "－ Remove empty set": persist the
    combo's planned set count. The derivation never renders fewer rows
    than are already logged (or the protocol default), so a too-small
    count simply has no effect. Adding a set to a Finished session reopens
    it for that set -- Finish is stamped again from the new summary."""
    require_grip_type(session, grip_type_id)
    training_session = start_or_get_session(session, user, date, session_number)
    before = planned_set_count(
        session, user, grip_type_id, edge_mm, date, session_number, None
    )
    stamp_play_combo(session, training_session, grip_type_id, edge_mm, commit=False)
    training_session.planned_sets = sets
    if sets > before:
        training_session.finished_at = None
    session.add(training_session)
    session.commit()
    session.refresh(training_session)
    return training_session


def commit_focus_set(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    set_number: int,
    session_number: int | None,
    hands_payload: dict[str, tuple[float, int, float | None]],
    editing: bool = False,
    sets_hint: int | None = None,
) -> TrainingSession:
    """Set commit (docs/adr/0007-set-commit-over-per-cell-autosave.md):
    writes both hands' WorkSets for one set_number in a single atomic
    transaction. Validates grip type, finds/starts session, stages both hands
    with record_work_set(commit=False), commits atomically, and returns the
    training session.

    Session play (#146, docs/adr/0014, orchestrator decision 1): a normal
    (non-editing) commit that isn't the last planned set starts the rest
    step by stamping rest_ends_at = now + TrainingProtocol.default_rest_seconds;
    a normal commit of the final planned set, or any edit-mode Save, leaves
    rest_ends_at untouched (an edit-mode Save must never (re)start a rest the
    user wasn't actually taking)."""
    require_grip_type(session, grip_type_id)
    training_session = start_or_get_session(session, user, date, session_number)
    if not editing:
        stamp_play_combo(
            session, training_session, grip_type_id, edge_mm, sets_hint, commit=False
        )
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
    session.refresh(training_session)
    if not editing:
        total_sets = planned_set_count(
            session, user, grip_type_id, edge_mm, date, session_number, sets_hint
        )
        if set_number < total_sets:
            protocol = get_protocol(session, user)
            training_session.rest_ends_at = utcnow() + timedelta(
                seconds=protocol.default_rest_seconds
            )
        else:
            training_session.rest_ends_at = None
        session.add(training_session)
        session.commit()
        session.refresh(training_session)
    return training_session


def _aware(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime (SQLite drops tzinfo on
    round-trip) to UTC-aware, so rest_ends_at comparisons against utcnow()
    are always apples-to-apples."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone

        return dt.replace(tzinfo=timezone.utc)
    return dt


def duration_minutes(start: datetime | None, end: datetime | None) -> float | None:
    """Minutes from `start` to `end` (fractional), or None if either is
    missing. Naive and aware datetimes are both read as UTC (SQLite drops
    tzinfo on the round trip), and a negative span (clock skew) clamps to
    0 rather than producing a negative duration."""
    start_aware, end_aware = _aware(start), _aware(end)
    if start_aware is None or end_aware is None:
        return None
    return max(0.0, (end_aware - start_aware).total_seconds() / 60)


def set_session_rpe(
    session: Session, training_session: TrainingSession, session_rpe: int
) -> None:
    """Session RPE (#147): the summary's whole-session effort chip. The
    router has already bounded the value (limits.MIN/MAX_SESSION_RPE);
    re-tapping another chip just overwrites it."""
    training_session.session_rpe = session_rpe
    session.add(training_session)
    session.commit()


def finish_session(session: Session, training_session: TrainingSession) -> None:
    """Finish (#147): stamp finished_at once. Idempotent -- a second tap (or
    a replayed POST) never moves an already-set finished_at, so session
    duration and session load stay anchored to the first Finish."""
    if training_session.finished_at is None:
        training_session.finished_at = utcnow()
        session.add(training_session)
        session.commit()


def summary_view(ws: dict, hands: list[str]) -> dict:
    """The Summary step's readouts (#147), computed from the worksets_view
    data play_view already loaded: TrainingVolume (Σ weight × reps) for
    this combo in this session, sets per hand, the mean of the logged set
    RPEs, the duration so far (to finished_at, or to now while unfinished),
    and the current tweak (PainReport) per hand."""
    saved = [w for (h, _n), w in ws["saved"].items() if h in hands]
    volume = sum(w.weight * w.reps for w in saved)
    per_hand = {h: sum(1 for w in saved if w.hand == h) for h in hands}
    counts = [c for c in per_hand.values() if c]
    rpes = [w.rpe for w in saved if w.rpe is not None]
    training_session = ws["training_session"]
    minutes = None
    if training_session is not None:
        minutes = duration_minutes(
            training_session.started_at, training_session.finished_at or utcnow()
        )
    tweaks = {r.hand: r for r in ws["pain_reports"] if r.hand in ("left", "right")}
    return {
        "volume": volume,
        # 1,405 / 212.5 -- thousands separator, and no ".0" on whole numbers.
        "volume_display": f"{volume:,.1f}".removesuffix(".0"),
        "sets_per_hand": per_hand,
        "sets_per_hand_uniform": counts[0] if counts and len(set(counts)) == 1 else None,
        "avg_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
        "duration_minutes": int(minutes) if minutes is not None else None,
        "session_rpe": training_session.session_rpe if training_session else None,
        "finished": bool(training_session and training_session.finished_at),
        "tweaks": tweaks,
        "tweak_hand": next((h for h in ("left", "right") if h in tweaks), "none"),
    }


def extend_rest(training_session: TrainingSession, session: Session, seconds: int = 30) -> None:
    """The "+30 s" action: push rest_ends_at later. If rest had already been
    cleared (or never started) there's nothing to extend -- a stale/duplicate
    tap is a no-op rather than starting a fresh rest."""
    current = _aware(training_session.rest_ends_at)
    if current is None:
        return
    # Bounded (PR #154 review MUST-FIX 7): never more than
    # MAX_REST_SECONDS + MAX_REST_EXTENSION_SECONDS ahead of now.
    latest = utcnow() + timedelta(seconds=MAX_REST_SECONDS + MAX_REST_EXTENSION_SECONDS)
    training_session.rest_ends_at = min(current + timedelta(seconds=seconds), latest)
    session.add(training_session)
    session.commit()


def clear_rest(training_session: TrainingSession, session: Session) -> None:
    """Skip rest / Start set N: both end the rest step immediately."""
    if training_session.rest_ends_at is not None:
        training_session.rest_ends_at = None
        session.add(training_session)
        session.commit()


def set_rest_sound(session: Session, user: User, on: bool) -> None:
    """The per-user Rest sound setting (#148, docs/adr/0015): whether the
    native rest-over alert also plays a sound. Never touches a pending
    rest."""
    user.rest_sound = on
    session.add(user)
    session.commit()


def rest_bridge_payload(
    user: User, ws: dict, rest_ends_at: datetime | None
) -> dict | None:
    """What the rest step hands `window.GripTrackNative.startRest(...)`
    (#148, docs/adr/0015): the rest end as epoch milliseconds plus the
    lock-screen notification's lines -- the countdown title, the next set's
    loads (hands in play order, native unit), and the rest-over line. None
    when no rest is pending."""
    if rest_ends_at is None:
        return None
    next_set = ws["current_set_number"]
    weights = [ws["seed"][h]["weight"] for h in ws["hands"]]
    loads = " / ".join("–" if w is None else f"{w:g}" for w in weights)
    return {
        "ends_at_ms": int(rest_ends_at.timestamp() * 1000),
        "title": f"Rest · set {next_set} of {ws['total_sets']} next",
        "detail": f"{loads} {user.unit_pref}",
        "ready": f"Pull. Set {next_set} is ready",
        "sound": bool(user.rest_sound),
    }


@dataclass
class PlayStep:
    """The one thing /session/play's step derivation hands the router: what
    to render, and the top bar's k/N counter. Everything else the step's
    template needs is read straight off the warmup_view/worksets_view dicts
    play_view returns alongside this."""

    kind: str  # "warmup" | "workset" | "rest" | "summary"
    step_number: int  # 1-based position in the combined rung+set sequence
    total_steps: int
    title: str


def play_view(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None,
    session_number: int | None,
    sets_hint: int | None = None,
    edit_set: int | None = None,
) -> dict:
    """Everything /session/play renders for the current step, in one call
    (see CLAUDE.md orchestrator decision 9): derives which step (warmup rung,
    work set, rest, summary) the session is on purely from persisted state
    (docs/adr/0014) and hands back both that derivation (as `step`) and the
    full warmup/worksets view data the step templates read from."""
    w = warmup_view(session, user, grip_type_id, edge_mm, date, hand, session_number)
    ws = worksets_view(
        session, user, grip_type_id, edge_mm, date, hand, sets_hint,
        session_number, edit_set,
    )
    inventory = plates.inventory_for(session, user)
    total_rungs = len(w["steps"])
    total_sets = ws["total_sets"]
    total_steps = total_rungs + total_sets
    training_session = ws["training_session"]
    # A pending rest belongs to the combo play is running (D2): another
    # combo opened in the same session never lands on its rest step.
    rest_ends_at = (
        _aware(training_session.rest_ends_at)
        if training_session is not None
        and is_play_combo(training_session, grip_type_id, edge_mm)
        else None
    )

    # warmup_view's own current_step is a *display* pill that caps at
    # total_rungs even once every rung is ticked (it never reads "5 of 4"),
    # so completeness has to be checked directly against the ticks rather
    # than by comparing current_step to total_rungs. Once any work set is
    # already committed for this combo/session, warmup is never shown again
    # even with unticked rungs -- logging a set is itself strong evidence
    # training has moved on (retro-logging, an import, a set saved by some
    # other path), and a stale warmup gate must never trap a session with
    # real data on it.
    warmup_complete = bool(w["steps"]) and all(
        (h, s["index"]) in w["checks"] for h in w["planned_hands"] for s in w["steps"]
    )
    has_any_workset = bool(ws["saved"])
    warmup_incomplete = bool(w["untested_hands"]) or (
        not has_any_workset and not warmup_complete
    )

    # Finish (#147) pins the session to its summary on resume -- even if a
    # set is later deleted -- as long as this view's hand(s) actually
    # logged something. Two deliberate escape hatches: a not-yet-persisted
    # sets= initialiser (⋯ "＋ Add a set" itself un-finishes the session,
    # see set_planned_sets), and a sequential-order
    # other hand with nothing logged yet (its "Start {other} hand" link
    # still runs that hand's warmup/sets normally).
    finished = training_session is not None and training_session.finished_at is not None
    view_has_sets = any(h in ws["hands"] for (h, _n) in ws["saved"])

    if ws["editing"]:
        kind = "workset"
        step_number = total_rungs + ws["display_set_number"]
    elif finished and view_has_sets and ws["sets_init"] is None:
        kind = "summary"
        step_number = total_steps
    elif warmup_incomplete:
        kind = "warmup"
        step_number = w["current_step"] if w["steps"] else 1
    elif rest_ends_at is not None:
        kind = "rest"
        step_number = total_rungs + min(ws["current_set_number"], total_sets or 1)
    elif ws["current_set_number"] > total_sets:
        kind = "summary"
        step_number = total_steps
    else:
        kind = "workset"
        step_number = total_rungs + ws["display_set_number"]

    workset_title = (
        f"Editing set {ws['display_set_number']}"
        if ws["editing"]
        else f"Work set {ws['display_set_number']} of {total_sets}"
    )
    titles = {
        "warmup": "Warmup",
        "workset": workset_title,
        "rest": "Rest",
        "summary": "Session",
    }
    step = PlayStep(
        kind=kind,
        step_number=max(step_number, 1),
        total_steps=max(total_steps, 1),
        title=titles[kind],
    )
    remaining_seconds = None
    if rest_ends_at is not None:
        remaining_seconds = max(0, int((rest_ends_at - utcnow()).total_seconds()))

    other_hand = (
        ("right" if w["hands"][0] == "left" else "left")
        if len(w["hands"]) == 1
        else None
    )
    # Sequential order: the other hand is still "left to do" until it has
    # logged every planned set -- only then does Finish become the summary's
    # primary action instead of "Start {other} hand".
    other_hand_pending = other_hand is not None and (
        sum(1 for (h, _n) in ws["saved"] if h == other_hand) < total_sets
    )

    return {
        "warmup": w,
        "worksets": ws,
        "step": step,
        "rest_ends_at": rest_ends_at,
        "rest_remaining_seconds": remaining_seconds,
        "rest_bridge": rest_bridge_payload(user, ws, rest_ends_at),
        "grip": w["grip"],
        "edge_mm": edge_mm,
        "date": date,
        "hands": w["hands"],
        # A single scalar for the hidden `hand` field every play form
        # carries: the sequential-mode active hand, or "" in alternating
        # mode (mirrors the pre-#146 warmup/worksets combo_redirect usage).
        "hand": w["hands"][0] if len(w["hands"]) == 1 else "",
        # Sequential HandOrderPreference runs one hand's whole flow at a
        # time; the other hand is where the "Switch to"/"Start" links go.
        "other_hand": other_hand,
        "other_hand_pending": other_hand_pending,
        # Session-level readouts: both hands' sets for this combo, even
        # on a sequential-order hand's summary.
        "summary": summary_view(ws, ["left", "right"]) if kind == "summary" else None,
        "session_number": w["session_number"],
        "training_session": training_session,
        "sets_init": ws["sets_init"],
        "inventory": inventory,
    }


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


def complete_warmup_rung(
    session: Session,
    training_session: TrainingSession,
    hands: list[str],
    step_index: int,
) -> None:
    """The play warmup step's "Rung done" button: ticks every in-play hand's
    tile for this rung that isn't already checked (an already-ticked tile is
    left alone, so a rung ticked by hand first and then "Rung done" doesn't
    accidentally untoggle it -- unlike toggle_warmup_check, this never
    removes a check)."""
    existing = {
        (check.hand, check.step_index)
        for check in session.exec(
            select(WarmupStepCheck)
            .where(WarmupStepCheck.training_session_id == training_session.id)
            .where(WarmupStepCheck.step_index == step_index)
        )
    }
    for hand in hands:
        if (hand, step_index) not in existing:
            session.add(
                WarmupStepCheck(
                    training_session_id=training_session.id,
                    hand=hand,
                    step_index=step_index,
                )
            )
    session.commit()


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


def save_protocol(
    session: Session, user: User, base_work_set_reps: int, default_rest_seconds: int
) -> TrainingProtocol:
    """Upsert the user's own TrainingProtocol row (Settings → Training):
    the rep target and default rest. The global default row is never
    touched; the ramp percentages stay global (ADR-0005)."""
    protocol = session.exec(
        select(TrainingProtocol).where(TrainingProtocol.user_id == user.id)
    ).first()
    if protocol is None:
        protocol = TrainingProtocol(user_id=user.id)
    protocol.base_work_set_reps = base_work_set_reps
    protocol.default_rest_seconds = default_rest_seconds
    session.add(protocol)
    session.commit()
    return protocol


def set_hand_order(session: Session, user: User, hand_order_pref: str) -> None:
    """Settings → Training: the user's HandOrderPreference. Callers
    validate against VALID_HAND_ORDER_PREFS first."""
    user.hand_order_pref = hand_order_pref
    session.add(user)
    session.commit()


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


def max_test_history(
    session: Session, user: User
) -> list[tuple[MaxWeightTest, GripType]]:
    """All MaxWeightTests for the user (including voided tests), paired with
    their GripType, ordered newest first (date desc, then id desc)."""
    return list(
        session.exec(
            select(MaxWeightTest, GripType)
            .join(GripType)
            .where(MaxWeightTest.user_id == user.id)
            .order_by(MaxWeightTest.date.desc(), MaxWeightTest.id.desc())
        ).all()
    )


def void_max_weight_test(
    session: Session, user: User, test_id: int
) -> MaxWeightTest | None:
    """Flag a MaxWeightTest as voided (bad data).

    Returns the updated MaxWeightTest, or None if the test is not found or
    does not belong to the user.
    """
    test = session.get(MaxWeightTest, test_id)
    if test is None or test.user_id != user.id:
        return None
    if test.voided_at is None:
        test.voided_at = utcnow()
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


def _find_progression_row(
    session: Session,
    user: User,
    grip_type_id: int | None,
    edge_mm: int | None,
) -> ProgressionSettings | None:
    """The ProgressionSettings row for a specific combo, or the user-level
    default row when grip/edge are None. A combo lookup needs BOTH grip_type_id
    and edge_mm; a partial pair falls through to the null-column default,
    matching the TrainingProtocol null-default convention (ADR-0012)."""
    query = select(ProgressionSettings).where(
        ProgressionSettings.user_id == user.id
    )
    if grip_type_id is not None and edge_mm is not None:
        query = query.where(
            ProgressionSettings.grip_type_id == grip_type_id
        ).where(ProgressionSettings.edge_mm == edge_mm)
    else:
        query = query.where(
            ProgressionSettings.grip_type_id.is_(None)
        ).where(ProgressionSettings.edge_mm.is_(None))
    return session.exec(query).first()


def get_progression_settings(
    session: Session,
    user: User,
    grip_type_id: int | None = None,
    edge_mm: int | None = None,
) -> ProgressionSettings:
    """The progression settings for a (user, grip_type, edge_mm), falling
    back to the user-level default row, else defaults derived from the
    protocol (ADR-0012)."""
    if grip_type_id is not None and edge_mm is not None:
        setting = _find_progression_row(session, user, grip_type_id, edge_mm)
        if setting is not None:
            return setting

    user_default = _find_progression_row(session, user, None, None)
    if user_default is not None:
        return user_default

    protocol = get_protocol(session, user)
    return ProgressionSettings(
        user_id=user.id,
        grip_type_id=None,
        edge_mm=None,
        path="weight",
        rep_min=protocol.base_work_set_reps,
        rep_max=protocol.base_work_set_reps,
        max_sets=6,
    )


def list_progression_settings(
    session: Session, user: User
) -> list[ProgressionSettings]:
    """All ProgressionSettings rows for this user."""
    return list(
        session.exec(
            select(ProgressionSettings)
            .where(ProgressionSettings.user_id == user.id)
            .order_by(ProgressionSettings.grip_type_id, ProgressionSettings.edge_mm)  # type: ignore[arg-type]
        ).all()
    )


def save_progression_settings(
    session: Session,
    user: User,
    path: str,
    rep_min: int,
    rep_max: int,
    max_sets: int,
    grip_type_id: int | None = None,
    edge_mm: int | None = None,
) -> ProgressionSettings:
    """Upsert progression settings for user default or specific combo."""
    is_combo = grip_type_id is not None and edge_mm is not None
    setting = _find_progression_row(session, user, grip_type_id, edge_mm)
    if setting is None:
        setting = ProgressionSettings(
            user_id=user.id,
            grip_type_id=grip_type_id if is_combo else None,
            edge_mm=edge_mm if is_combo else None,
        )
    setting.path = path
    setting.rep_min = rep_min
    setting.rep_max = rep_max
    setting.max_sets = max_sets

    session.add(setting)
    session.commit()
    session.refresh(setting)
    return setting


def delete_progression_settings(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
) -> bool:
    """Remove a per-combo progression override."""
    setting = _find_progression_row(session, user, grip_type_id, edge_mm)
    if setting is not None:
        session.delete(setting)
        session.commit()
        return True
    return False


PAIN_REPORT_HANDS = ("left", "right", "both")


def record_pain_report(
    session: Session,
    training_session: TrainingSession,
    hand: str,
    severity: int,
    note: str | None,
) -> PainReport:
    """Upsert one PainReport (see CONTEXT.md: PainReport) -- at most one row
    per (session, hand). The play "How did it feel?" disclosure autosaves its
    severity and note independently, so this must update in place rather
    than always inserting; the Today ＋ Log sheet's Tweak tab (#149) shares
    the same write."""
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
    session.refresh(report)
    return report


def log_bodyweight(
    session: Session, user: User, date: date_type, weight: float
) -> BodyWeightLog:
    """Append one BodyWeightLog entry (a time series, never a mutable profile
    field -- ADR-0001). Shared by the profile form and the ＋ Log sheet's
    Bodyweight tab (#149)."""
    entry = BodyWeightLog(user_id=user.id, date=date, weight=weight)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry
