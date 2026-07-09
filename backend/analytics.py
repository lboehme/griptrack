import re
import statistics
from datetime import date as date_type

from sqlmodel import Session, select

from backend import training_log
from backend.models import (
    Climb,
    MaxWeightTest,
    TrainingSession,
    User,
    WorkSet,
)

# Heuristic tuning (see CONTEXT.md: Plateau / OvertrainingWarning).
# Deliberately simple: revisit once real data exists.
PLATEAU_RECENT_SESSIONS = 4
OVERTRAINING_TRAILING_SESSIONS = 4
OVERTRAINING_SPIKE_FACTOR = 1.25


# Standard Font -> V-scale conversion (approximate, as all such tables are).
# The correlation runs on the V-number axis; V grades parse directly.
FONT_TO_V = {
    "4": 0, "4+": 0, "5": 1, "5+": 2,
    "6A": 3, "6A+": 3, "6B": 4, "6B+": 4, "6C": 5, "6C+": 5,
    "7A": 6, "7A+": 7, "7B": 8, "7B+": 8, "7C": 9, "7C+": 10,
    "8A": 11, "8A+": 12, "8B": 13, "8B+": 14, "8C": 15, "8C+": 16,
    "9A": 17,
}


def parse_boulder_grade(grade: str) -> float | None:
    """Numeric (V-scale) value of a boulder grade string; V and Font
    supported, anything else excluded from analysis (still logged)."""
    text = grade.strip().upper()
    v_match = re.fullmatch(r"V(\d{1,2})", text)
    if v_match:
        return float(v_match.group(1))
    if text in FONT_TO_V:
        return float(FONT_TO_V[text])
    return None


def _best_pull_at(session: Session, user: User, date: date_type) -> float | None:
    """The user's best CurrentMax across all combos as of a date — the
    supersede rule itself lives in training_log.compute_current_max."""
    # Combos the user has tested (voided tests are excluded from the strength signal).
    combos = session.exec(
        select(
            MaxWeightTest.hand, MaxWeightTest.grip_type_id, MaxWeightTest.edge_mm
        )
        .where(MaxWeightTest.user_id == user.id)
        .where(MaxWeightTest.voided_at.is_(None))
        .distinct()
    ).all()
    values = [
        training_log.compute_current_max(
            session, user, hand, grip_type_id, edge_mm, as_of=date
        )
        for hand, grip_type_id, edge_mm in combos
    ]
    return max((v for v in values if v is not None), default=None)


def strength_grade_correlation(session: Session, user: User) -> dict:
    """%bodyweight strength vs boulder grade, framed against Lattice's
    published methodology as a reference point — not a reproduction (their
    research covers hangboard hangs, not block pulls). Sport climbs and
    unparseable grades are excluded; needs 3+ points with variance."""
    climbs = session.exec(
        select(Climb)
        .where(Climb.user_id == user.id)
        .where(Climb.discipline == "boulder")
        .order_by(Climb.date)
    ).all()

    points = []
    for climb in climbs:
        grade_value = parse_boulder_grade(climb.grade)
        bodyweight = training_log.bodyweight_at(session, user, as_of=climb.date)
        strength = _best_pull_at(session, user, climb.date)
        if grade_value is None or bodyweight is None or strength is None:
            continue
        points.append(
            {
                "date": climb.date,
                "pct_bodyweight": strength / bodyweight.weight,
                "grade_value": grade_value,
                "grade": climb.grade,
            }
        )

    result = {"points": points, "n": len(points), "r": None}
    pcts = [point["pct_bodyweight"] for point in points]
    grades = [point["grade_value"] for point in points]
    if len(points) >= 3 and len(set(pcts)) > 1 and len(set(grades)) > 1:
        result["r"] = statistics.correlation(pcts, grades)
    return result


def training_volume_trend(
    session: Session, user: User, hand: str, grip_type_id: int, edge_mm: int
) -> list[tuple[date_type, float]]:
    """TrainingVolume (Σ weight × reps) per TrainingSession for one combo,
    oldest first. Grouped by (date, session_number) rather than date alone
    — two sessions on the same date (see CLAUDE.md: multi-session days)
    stay independent points rather than merging into one."""
    rows = session.exec(
        select(
            TrainingSession.date,
            TrainingSession.session_number,
            WorkSet.weight,
            WorkSet.reps,
        )
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(TrainingSession.is_deload == False)
        .order_by(TrainingSession.date, TrainingSession.session_number)
    ).all()
    volumes: dict[tuple[date_type, int], float] = {}
    for date, session_number, weight, reps in rows:
        key = (date, session_number)
        volumes[key] = volumes.get(key, 0.0) + weight * reps
    return [(date, volume) for (date, _session_number), volume in sorted(volumes.items())]


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
