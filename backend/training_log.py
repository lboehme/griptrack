from datetime import date as date_type

from sqlmodel import Session, select

from backend import plates
from backend.models import (
    MaxWeightTest,
    TrainingProtocol,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
)


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


def record_warmup_check(
    session: Session, training_session: TrainingSession, hand: str, step_index: int
) -> None:
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
    session: Session, user: User, hand: str, grip_type_id: int, edge_mm: int
) -> MaxWeightTest | None:
    return session.exec(
        select(MaxWeightTest)
        .where(MaxWeightTest.user_id == user.id)
        .where(MaxWeightTest.hand == hand)
        .where(MaxWeightTest.grip_type_id == grip_type_id)
        .where(MaxWeightTest.edge_mm == edge_mm)
        .order_by(MaxWeightTest.date.desc(), MaxWeightTest.id.desc())
    ).first()


def compute_current_max(
    session: Session, user: User, hand: str, grip_type_id: int, edge_mm: int
) -> float | None:
    """CurrentMax: the heavier of the latest MaxWeightTest and the heaviest
    WorkSet logged since that test (see CONTEXT.md: CurrentMax).

    A newer test supersedes everything before it, even when lower
    (deliberate reset) — work sets predating the latest test never count.
    Returns None when the combination has never been tested.
    """
    test = latest_max_test(session, user, hand, grip_type_id, edge_mm)
    if test is None:
        return None
    heaviest_since = session.exec(
        select(WorkSet)
        .join(TrainingSession, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date >= test.date)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .order_by(WorkSet.weight.desc())
    ).first()
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


def tested_combinations(session: Session, user: User) -> list[dict]:
    """One entry per tested (hand, grip_type, edge_mm), with its CurrentMax."""
    tests = session.exec(
        select(MaxWeightTest).where(MaxWeightTest.user_id == user.id)
    ).all()
    combos = sorted({(t.hand, t.grip_type_id, t.edge_mm) for t in tests})
    return [
        {
            "hand": hand,
            "grip_type_id": grip_type_id,
            "edge_mm": edge_mm,
            "current_max": compute_current_max(
                session, user, hand, grip_type_id, edge_mm
            ),
        }
        for hand, grip_type_id, edge_mm in combos
    ]
