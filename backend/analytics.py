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


def _rank(values: list[float]) -> list[float]:
    """Assigns ranks to a list of values, averaging the ranks for ties."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        val = indexed[i][1]
        j = i
        while j < len(indexed) and indexed[j][1] == val:
            j += 1
        avg_rank = sum(range(i + 1, j + 1)) / (j - i)
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def strength_grade_correlation(session: Session, user: User) -> dict:
    """%bodyweight strength vs boulder grade, framed against Lattice's
    published methodology as a reference point — not a reproduction (their
    research covers hangboard hangs, not block pulls). Sport climbs and
    unparseable grades are excluded; needs 8+ points with variance."""
    climbs = session.exec(
        select(Climb)
        .where(Climb.user_id == user.id)
        .where(Climb.discipline == "boulder")
        .order_by(Climb.date)  # type: ignore[arg-type]  # SQLModel column typed as date, not Column
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
    # points is list[dict[str, object]] (mixed-type dict) so the comprehension
    # can't statically prove the values back out as float — they are, by
    # construction just above.
    pcts: list[float] = [point["pct_bodyweight"] for point in points]  # type: ignore[misc]
    grades: list[float] = [point["grade_value"] for point in points]  # type: ignore[misc]
    if len(points) >= 8 and len(set(pcts)) > 1 and len(set(grades)) > 1:
        # Spearman rank correlation is the Pearson correlation of the ranks.
        result["r"] = statistics.correlation(_rank(pcts), _rank(grades))
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
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(TrainingSession.is_deload.is_(False))
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

    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
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


def strength_gap_trend(
    session: Session, user: User, grip_type_id: int, edge_mm: int
) -> list[tuple[date_type, float]]:
    """Signed strength gap trend ((L - R) / max(L, R) * 100.0) per date for
    a (grip_type_id, edge_mm) combination, oldest first.

    Evaluated on distinct dates where the user logged a WorkSet or non-voided
    MaxWeightTest for this grip and edge on either hand. Points only exist
    when both hands have a non-None, positive CurrentMax as of that date.
    """
    workset_dates = session.exec(
        select(TrainingSession.date)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .distinct()
    ).all()

    test_dates = session.exec(
        select(MaxWeightTest.date)
        .where(MaxWeightTest.user_id == user.id)
        .where(MaxWeightTest.voided_at.is_(None))
        .where(MaxWeightTest.grip_type_id == grip_type_id)
        .where(MaxWeightTest.edge_mm == edge_mm)
        .distinct()
    ).all()

    dates = sorted(set(workset_dates) | set(test_dates))

    trend: list[tuple[date_type, float]] = []
    for d in dates:
        left_max = training_log.compute_current_max(
            session, user, "left", grip_type_id, edge_mm, as_of=d
        )
        right_max = training_log.compute_current_max(
            session, user, "right", grip_type_id, edge_mm, as_of=d
        )
        if (
            left_max is not None
            and right_max is not None
            and left_max > 0
            and right_max > 0
        ):
            m = max(left_max, right_max)
            gap = (left_max - right_max) / m * 100.0
            trend.append((d, gap))

    return trend


def dashboard_view(session: Session, user: User) -> dict:
    """Everything the trends/dashboard page shows, assembled in one call.
    Finds trained combinations, computes training volume trends, evaluates
    plateau and overtraining heuristics, formats client chart data,
    calculates strength-to-grade correlation, and computes bilateral
    strength asymmetry gap trends."""
    combos = []
    trained = training_log.trained_combinations(session, user)
    for combo in trained:
        trend = training_volume_trend(
            session, user, combo["hand"], combo["grip_type_id"], combo["edge_mm"]
        )
        if not trend:
            continue
        combos.append(
            {
                **combo,
                # Built once here rather than re-joined per attribute in the
                # template (plateau/overtraining pills, volume-list rows,
                # the chart container, and the chart_data payload below all
                # need the same "hand|grip_name|edge_mm" key).
                "combo_key": f"{combo['hand']}|{combo['grip_name']}|{combo['edge_mm']}",
                "trend": trend,
                "plateau": plateau_flag(trend),
                "overtraining": overtraining_warning(trend),
            }
        )
    # Fed to the client-side uPlot chart via the JSON-in-DOM idiom (see
    # worksets.html's ladder-data/saved-sets-data precedent) -- one entry
    # per trained combo, dates serialized to ISO strings since Jinja's
    # tojson can't encode date objects directly.
    chart_data = [
        {
            "combo": combo["combo_key"],
            "dates": [d.isoformat() for d, _ in combo["trend"]],
            "volumes": [v for _, v in combo["trend"]],
        }
        for combo in combos
    ]

    # Bilateral asymmetry: identify (grip_type_id, edge_mm) pairs trained by
    # both hands and compute strength gap trend.
    grip_edges: dict[tuple[int, int], dict[str, str]] = {}
    hands_by_grip_edge: dict[tuple[int, int], set[str]] = {}
    for c in trained:
        key = (c["grip_type_id"], c["edge_mm"])
        hands_by_grip_edge.setdefault(key, set()).add(c["hand"])
        if key not in grip_edges:
            grip_edges[key] = {
                "grip_name": c["grip_name"],
                "dimension_name": c["dimension_name"],
            }

    asymmetry_pairs = []
    for (grip_type_id, edge_mm), hands in sorted(hands_by_grip_edge.items()):
        if "left" in hands and "right" in hands:
            asym_trend = strength_gap_trend(session, user, grip_type_id, edge_mm)
            if not asym_trend:
                continue
            meta = grip_edges[(grip_type_id, edge_mm)]
            combo_key = f"asymmetry|{meta['grip_name']}|{edge_mm}"
            asymmetry_pairs.append(
                {
                    "grip_type_id": grip_type_id,
                    "grip_name": meta["grip_name"],
                    "dimension_name": meta["dimension_name"],
                    "edge_mm": edge_mm,
                    "combo_key": combo_key,
                    "trend": asym_trend,
                }
            )

    asymmetry_chart_data = [
        {
            "combo": pair["combo_key"],
            "grip_name": pair["grip_name"],
            "edge_mm": pair["edge_mm"],
            "dates": [d.isoformat() for d, _ in pair["trend"]],
            "gaps": [g for _, g in pair["trend"]],
        }
        for pair in asymmetry_pairs
    ]

    return {
        "combos": combos,
        "chart_data": chart_data,
        "correlation": strength_grade_correlation(session, user),
        "asymmetry_pairs": asymmetry_pairs,
        "asymmetry_chart_data": asymmetry_chart_data,
    }

