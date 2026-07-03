from datetime import date as date_type

from sqlmodel import Session, select

from backend.models import TrainingSession, User, WorkSet

# Plateau heuristic tuning (see CONTEXT.md: Plateau). Deliberately simple:
# revisit once real data exists.
PLATEAU_RECENT_SESSIONS = 4


def training_volume_trend(
    session: Session, user: User, hand: str, grip_type_id: int, edge_mm: int
) -> list[tuple[date_type, float]]:
    """TrainingVolume (Σ weight × reps) per TrainingSession for one combo,
    oldest first."""
    rows = session.exec(
        select(TrainingSession.date, WorkSet.weight, WorkSet.reps)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .order_by(TrainingSession.date)
    ).all()
    volumes: dict[date_type, float] = {}
    for date, weight, reps in rows:
        volumes[date] = volumes.get(date, 0.0) + weight * reps
    return sorted(volumes.items())


def plateau_flag(trend: list[tuple[date_type, float]]) -> bool:
    """Plateau: the last PLATEAU_RECENT_SESSIONS sessions never exceeded the
    best volume of the sessions before them — sustained lack of growth.
    Needs enough history to be meaningful."""
    if len(trend) < PLATEAU_RECENT_SESSIONS + 2:
        return False
    volumes = [volume for _, volume in trend]
    recent = volumes[-PLATEAU_RECENT_SESSIONS:]
    earlier = volumes[:-PLATEAU_RECENT_SESSIONS]
    return max(recent) <= max(earlier)
