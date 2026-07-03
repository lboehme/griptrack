from datetime import date as date_type

from sqlmodel import Session, select

from backend.models import TrainingSession, User, WorkSet

# Heuristic tuning (see CONTEXT.md: Plateau / OvertrainingWarning).
# Deliberately simple: revisit once real data exists.
PLATEAU_RECENT_SESSIONS = 4
OVERTRAINING_TRAILING_SESSIONS = 4
OVERTRAINING_SPIKE_FACTOR = 1.25


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


def overtraining_warning(trend: list[tuple[date_type, float]]) -> bool:
    """OvertrainingWarning: the latest session is BOTH a volume spike above
    the trailing average AND came after a shorter-than-typical rest —
    neither signal alone fires (see CONTEXT.md: OvertrainingWarning)."""
    if len(trend) < OVERTRAINING_TRAILING_SESSIONS + 1:
        return False
    window = trend[-(OVERTRAINING_TRAILING_SESSIONS + 1):]
    dates = [date for date, _ in window]
    volumes = [volume for _, volume in window]

    trailing_average = sum(volumes[:-1]) / len(volumes[:-1])
    volume_spike = volumes[-1] >= OVERTRAINING_SPIKE_FACTOR * trailing_average

    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    typical_rest = sum(gaps[:-1]) / len(gaps[:-1])
    short_rest = gaps[-1] < typical_rest

    return volume_spike and short_rest


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
