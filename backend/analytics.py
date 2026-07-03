import re
import statistics
from datetime import date as date_type

from sqlmodel import Session, select

from backend.models import (
    BodyWeightLog,
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


def _bodyweight_at(session: Session, user: User, date: date_type) -> float | None:
    log = session.exec(
        select(BodyWeightLog)
        .where(BodyWeightLog.user_id == user.id)
        .where(BodyWeightLog.date <= date)
        .order_by(BodyWeightLog.date.desc(), BodyWeightLog.id.desc())
    ).first()
    return log.weight if log else None


def _best_pull_at(session: Session, user: User, date: date_type) -> float | None:
    """The user's best CurrentMax across all combos as of a date: per combo,
    the latest MaxWeightTest <= date, raised by any heavier WorkSet logged
    between that test and the date (same supersede rule as CurrentMax)."""
    tests = session.exec(
        select(MaxWeightTest)
        .where(MaxWeightTest.user_id == user.id)
        .where(MaxWeightTest.date <= date)
    ).all()
    latest_per_combo: dict[tuple, MaxWeightTest] = {}
    for test in tests:
        key = (test.hand, test.grip_type_id, test.edge_mm)
        current = latest_per_combo.get(key)
        if current is None or (test.date, test.id) > (current.date, current.id):
            latest_per_combo[key] = test

    if not latest_per_combo:
        return None

    best = None
    for (hand, grip_type_id, edge_mm), test in latest_per_combo.items():
        combo_max = test.weight
        heaviest = session.exec(
            select(WorkSet)
            .join(TrainingSession, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
            .where(TrainingSession.user_id == user.id)
            .where(TrainingSession.date >= test.date)
            .where(TrainingSession.date <= date)
            .where(WorkSet.hand == hand)
            .where(WorkSet.grip_type_id == grip_type_id)
            .where(WorkSet.edge_mm == edge_mm)
            .order_by(WorkSet.weight.desc())
        ).first()
        if heaviest is not None and heaviest.weight > combo_max:
            combo_max = heaviest.weight
        if best is None or combo_max > best:
            best = combo_max
    return best


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
        bodyweight = _bodyweight_at(session, user, climb.date)
        strength = _best_pull_at(session, user, climb.date)
        if grade_value is None or bodyweight is None or strength is None:
            continue
        points.append(
            {
                "date": climb.date,
                "pct_bodyweight": strength / bodyweight,
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
