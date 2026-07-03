from sqlmodel import Session, select

from backend.models import MaxWeightTest, User


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
    """CurrentMax: the latest MaxWeightTest for this combination.

    A newer test supersedes an older one even when lower (deliberate
    reset). Once WorkSets exist, a heavier work set logged since the
    latest test also raises this (see CONTEXT.md: CurrentMax).
    Returns None when the combination has never been tested.
    """
    test = latest_max_test(session, user, hand, grip_type_id, edge_mm)
    return test.weight if test is not None else None


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
