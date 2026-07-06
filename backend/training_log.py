from datetime import date as date_type

from sqlmodel import Session, select

from backend import plates
from backend.models import (
    BodyWeightLog,
    GripType,
    MaxWeightTest,
    TrainingProtocol,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
)


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
) -> dict:
    """Everything the warmup page shows, assembled in one call: ramp plans
    per hand (or which hands still need a MaxWeightTest), the step list,
    and the TrainingSession's persisted checks."""
    hands = hands_for(user, hand)
    plans = {
        h: compute_ramp_plan(session, user, h, grip_type_id, edge_mm)
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
    training_session = find_session(session, user, date)
    return {
        "grip": session.get(GripType, grip_type_id),
        "edge_mm": edge_mm,
        "date": date,
        "hands": hands,
        "plans": plans,
        "untested_hands": untested_hands,
        "steps": steps,
        "training_session": training_session,
        "checks": warmup_checks(session, training_session),
    }


def worksets_view(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hand: str | None = None,
    sets_hint: int | None = None,
) -> dict:
    """Everything the work-sets page shows: saved sets by (hand, set),
    prefills from CurrentMax and the TrainingProtocol, and the row math
    (default rows, add-another-set hint, dismissable empty rows)."""
    hands = hands_for(user, hand)
    protocol = get_protocol(session, user)
    saved = {
        (ws.hand, ws.set_number): ws
        for ws in worksets_for_combo(session, user, grip_type_id, edge_mm, date)
    }
    current_max = {
        h: compute_current_max(session, user, h, grip_type_id, edge_mm)
        for h in hands
    }
    highest_saved = max((n for _, n in saved), default=0)
    needed_rows = max(protocol.default_work_sets, highest_saved)
    row_count = max(needed_rows, sets_hint or 0)
    return {
        "grip": session.get(GripType, grip_type_id),
        "edge_mm": edge_mm,
        "date": date,
        "hands": hands,
        "set_numbers": list(range(1, row_count + 1)),
        "saved": saved,
        "current_max": current_max,
        "default_reps": protocol.base_work_set_reps,
        "more_sets": row_count + 1,
        # Extra empty rows (from "add another set") can be dismissed again.
        "removable_to": row_count - 1 if row_count > needed_rows else None,
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


def worksets_for_combo(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
) -> list[WorkSet]:
    training_session = find_session(session, user, date)
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
) -> WorkSet:
    """Upsert one work set — every field edit autosaves, so the same
    (hand, set_number) cell is written repeatedly within a session."""
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
    session.commit()
    session.refresh(work_set)
    return work_set


def start_or_get_session(
    session: Session, user: User, date: date_type
) -> TrainingSession:
    """The TrainingSession for this user+date, created on first use — a
    session exists from the first checkbox tap, there is no submit step."""
    training_session = session.exec(
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date == date)
    ).first()
    if training_session is None:
        training_session = TrainingSession(user_id=user.id, date=date)
        session.add(training_session)
        session.commit()
        session.refresh(training_session)
    return training_session


def find_session(
    session: Session, user: User, date: date_type
) -> TrainingSession | None:
    return session.exec(
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date == date)
    ).first()


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
    session: Session, user: User, hand: str, grip_type_id: int, edge_mm: int
) -> list[dict] | None:
    """Plate-rounded warmup/ramp steps for one hand, or None if untested."""
    current_max = compute_current_max(session, user, hand, grip_type_id, edge_mm)
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
    """Past TrainingSessions (newest first), each with its WorkSets."""
    sessions = session.exec(
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
        .order_by(TrainingSession.date.desc(), TrainingSession.id.desc())
    ).all()
    history = []
    for training_session in sessions:
        work_sets = session.exec(
            select(WorkSet)
            .where(WorkSet.training_session_id == training_session.id)
            .order_by(WorkSet.set_number, WorkSet.hand)
        ).all()
        history.append({"session": training_session, "work_sets": work_sets})
    return history


def grip_names(session: Session) -> dict[int, str]:
    """GripType id -> display name, for anything rendering WorkSets."""
    return {grip.id: grip.name for grip in session.exec(select(GripType))}


def tested_combinations(session: Session, user: User) -> list[dict]:
    """One entry per tested (hand, grip_type, edge_mm), with its CurrentMax
    and the grip's display name — callers never join names themselves."""
    tests = session.exec(
        select(MaxWeightTest).where(MaxWeightTest.user_id == user.id)
    ).all()
    combos = sorted({(t.hand, t.grip_type_id, t.edge_mm) for t in tests})
    names = grip_names(session)
    return [
        {
            "hand": hand,
            "grip_type_id": grip_type_id,
            "grip_name": names[grip_type_id],
            "edge_mm": edge_mm,
            "current_max": compute_current_max(
                session, user, hand, grip_type_id, edge_mm
            ),
        }
        for hand, grip_type_id, edge_mm in combos
    ]
