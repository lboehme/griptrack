import re
import statistics
from datetime import date as date_type

from sqlmodel import Session, select

from backend import plates, training_log
from backend.models import (
    Climb,
    MaxWeightTest,
    SessionMaxEstimate,
    TrainingSession,
    User,
    WorkSet,
)

# Heuristic tuning (see CONTEXT.md: Plateau / OvertrainingWarning / AsymmetryWarning / Nudges).
# Deliberately simple: revisit once real data exists.
PLATEAU_RECENT_SESSIONS = 4
OVERTRAINING_TRAILING_SESSIONS = 4
OVERTRAINING_SPIKE_FACTOR = 1.25
ASYM_RECENT_SESSIONS = 3
ASYM_BASELINE_SESSIONS = 6
ASYM_MIN_BASELINE_SESSIONS = 3
ASYM_DRIFT_PP = 5.0
ASYM_BACKSTOP_PCT = 15.0
RETEST_MIN_WEEKS = 8
ESTIMATE_NUDGE_COUNT = 3
# Autoregulation thresholds (issue #129, ADR-0011, ADR-0012).
AUTOREG_TRIGGER_SESSIONS = 2
AUTOREG_RPE_READY_MAX = 7.0
AUTOREG_RPE_HOLD_MIN = 9.0



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


def mean_intensity_trend(
    session: Session, user: User, hand: str, grip_type_id: int, edge_mm: int
) -> list[tuple[date_type, float]]:
    """Mean intensity (mean of weight ÷ compute_current_max(as_of=session.date)
    across working sets) per TrainingSession for one combo, oldest first.
    Grouped by (date, session_number). Sessions where CurrentMax is None
    (untested/estimate-only) are skipped; deloads are excluded."""
    rows = session.exec(
        select(
            TrainingSession.date,
            TrainingSession.session_number,
            WorkSet.weight,
        )
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(TrainingSession.is_deload.is_(False))
        .order_by(TrainingSession.date, TrainingSession.session_number)
    ).all()
    session_weights: dict[tuple[date_type, int], list[float]] = {}
    for date, session_number, weight in rows:
        key = (date, session_number)
        session_weights.setdefault(key, []).append(weight)

    trend: list[tuple[date_type, float]] = []
    for (date, _session_number), weights in sorted(session_weights.items()):
        current_max = training_log.compute_current_max(
            session, user, hand, grip_type_id, edge_mm, as_of=date
        )
        if current_max is not None and current_max > 0:
            mean_intensity = sum(w / current_max for w in weights) / len(weights)
            trend.append((date, mean_intensity))

    return trend


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


def signed_gap_pct(left: float, right: float) -> float:
    """Signed L/R gap as a percentage of the larger side:
    (left - right) / max(left, right) * 100.0. Positive means left is larger.
    Callers guarantee at least one side is positive."""
    return (left - right) / max(left, right) * 100.0


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
            trend.append((d, signed_gap_pct(left_max, right_max)))

    return trend


def load_gap_trend(
    session: Session, user: User, grip_type_id: int, edge_mm: int
) -> list[tuple[date_type, float]]:
    """Signed load/volume gap trend ((L - R) / max(L, R) * 100.0) per
    TrainingSession for a (grip_type_id, edge_mm) combination, oldest first.

    A point exists for each non-deload session where BOTH hands logged work
    sets at that combo in that session. (Sessions where only one hand trained
    the combo produce no point). Grouped by (date, session_number) and
    ordered chronologically.
    """
    rows = session.exec(
        select(
            TrainingSession.date,
            TrainingSession.session_number,
            WorkSet.hand,
            WorkSet.weight,
            WorkSet.reps,
        )
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(TrainingSession.is_deload.is_(False))
        .order_by(TrainingSession.date, TrainingSession.session_number)
    ).all()

    volumes: dict[tuple[date_type, int], dict[str, float]] = {}
    for date, session_number, hand, weight, reps in rows:
        key = (date, session_number)
        if key not in volumes:
            volumes[key] = {}
        volumes[key][hand] = volumes[key].get(hand, 0.0) + weight * reps

    trend: list[tuple[date_type, float]] = []
    for (date, _session_number), hand_map in sorted(volumes.items()):
        if "left" in hand_map and "right" in hand_map:
            # Per-hand volume is always positive when present (WorkSet weight
            # and reps are validated > 0), so max(left, right) > 0 always holds.
            trend.append((date, signed_gap_pct(hand_map["left"], hand_map["right"])))

    return trend


def asymmetry_warning(gap_trend: list[tuple[date_type, float]]) -> bool:
    """AsymmetryWarning: bilateral training load gap has widened by >= ASYM_DRIFT_PP
    percentage points compared to the user's personal baseline window, OR recent
    load asymmetry reaches/exceeds ASYM_BACKSTOP_PCT. Requires at least
    ASYM_RECENT_SESSIONS + ASYM_MIN_BASELINE_SESSIONS data points (thin data gates
    both arms). Narrowing gaps never warn."""
    if len(gap_trend) < ASYM_RECENT_SESSIONS + ASYM_MIN_BASELINE_SESSIONS:
        return False
    gaps = [abs(gap) for _, gap in gap_trend]
    recent = sum(gaps[-ASYM_RECENT_SESSIONS:]) / ASYM_RECENT_SESSIONS
    baseline_window = gaps[
        -(ASYM_RECENT_SESSIONS + ASYM_BASELINE_SESSIONS) : -ASYM_RECENT_SESSIONS
    ]
    baseline = sum(baseline_window) / len(baseline_window)
    if recent < baseline:
        return False
    return (recent - baseline >= ASYM_DRIFT_PP) or (recent >= ASYM_BACKSTOP_PCT)


def dashboard_view(session: Session, user: User) -> dict:
    """Everything the trends/dashboard page shows, assembled in one call.
    Finds trained combinations, computes training volume trends, evaluates
    plateau and overtraining heuristics, formats client chart data,
    calculates strength-to-grade correlation, and computes bilateral
    strength and load asymmetry gap trends."""
    combos = []
    trained = training_log.trained_combinations(session, user)
    for combo in trained:
        trend = training_volume_trend(
            session, user, combo["hand"], combo["grip_type_id"], combo["edge_mm"]
        )
        if not trend:
            continue
        intensity_trend = mean_intensity_trend(
            session, user, combo["hand"], combo["grip_type_id"], combo["edge_mm"]
        )
        combos.append(
            {
                **combo,
                # Built once here rather than re-joined per attribute in the
                # template (plateau/overtraining pills, volume-list rows,
                # the chart container, and the chart_data payload below all
                # need the same "hand|grip_name|edge_mm" key).
                "combo_key": f"{combo['hand']}|{combo['grip_name']}|{combo['edge_mm']}",
                "trend": trend,
                "intensity_trend": intensity_trend,
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
            "intensity_dates": [d.isoformat() for d, _ in combo["intensity_trend"]],
            "intensities": [i for _, i in combo["intensity_trend"]],
        }
        for combo in combos
    ]

    # Bilateral asymmetry: identify (grip_type_id, edge_mm) pairs trained or
    # tested by both hands and compute strength gap and load gap trends.
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
            strength_trend = strength_gap_trend(session, user, grip_type_id, edge_mm)
            load_trend = load_gap_trend(session, user, grip_type_id, edge_mm)
            if not strength_trend and not load_trend:
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
                    "strength_trend": strength_trend,
                    "load_trend": load_trend,
                    "asymmetry_warning": asymmetry_warning(load_trend),
                }
            )

    asymmetry_chart_data = [
        {
            "combo": pair["combo_key"],
            "grip_name": pair["grip_name"],
            "edge_mm": pair["edge_mm"],
            "strength_dates": [d.isoformat() for d, _ in pair["strength_trend"]],
            "strength_gaps": [g for _, g in pair["strength_trend"]],
            "load_dates": [d.isoformat() for d, _ in pair["load_trend"]],
            "load_gaps": [g for _, g in pair["load_trend"]],
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


def _next_rung_above(ladder: list[float], weight: float) -> float | None:
    """First loadable rung strictly heavier than `weight`, compared at
    cent precision to dodge float drift. None when nothing loads higher."""
    weight_cents = int(round(weight * 100))
    return next((r for r in ladder if int(round(r * 100)) > weight_cents), None)


def _format_weight(weight: float) -> str:
    """Trim a whole-number weight to no decimal point ('20' not '20.0')."""
    return f"{int(weight)}" if weight.is_integer() else f"{weight}"


def _weight_step_fields(
    user: User, current_weight: float, next_rung: float
) -> dict:
    """Shared payload for a '+one loadable increment' suggestion (Weight path
    and the Double weight-phase render the same fields)."""
    delta = round(next_rung - current_weight, 2)
    unit = user.unit_pref
    return {
        "current_weight": current_weight,
        "suggested_weight": next_rung,
        "increment": delta,
        "message": (
            f"Ready to progress: try {_format_weight(next_rung)} {unit} "
            f"(+{_format_weight(delta)} {unit})"
        ),
    }


def retest_nudge(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
) -> bool:
    """Retest nudge (ADR-0011): fires when compute_current_max exceeds the last
    MaxWeightTest.weight by >= one loadable increment (via plates.loadable_ladder)
    AND it has been >= RETEST_MIN_WEEKS (56 days) since that test's date.
    Suggests a guided MaxWeightTest; never auto-adjusts CurrentMax."""
    test = training_log.latest_max_test(
        session, user, hand, grip_type_id, edge_mm, as_of=as_of
    )
    if test is None:
        return False

    ref_date = as_of if as_of is not None else date_type.today()
    if (ref_date - test.date).days < RETEST_MIN_WEEKS * 7:
        return False

    current_max = training_log.compute_current_max(
        session, user, hand, grip_type_id, edge_mm, as_of=as_of
    )
    if current_max is None or current_max <= test.weight:
        return False

    inventory = plates.inventory_for(session, user)
    ladder = plates.loadable_ladder(inventory)
    next_rung = _next_rung_above(ladder, test.weight)
    if next_rung is None:
        return False

    return int(round(current_max * 100)) >= int(round(next_rung * 100))


def estimate_nudge(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
) -> bool:
    """Estimate nudge (ADR-0011): fires when a combo has NO MaxWeightTest but has
    accumulated a SessionMaxEstimate across >= ESTIMATE_NUDGE_COUNT (3) distinct
    sessions. Silent once a real test exists."""
    test = training_log.latest_max_test(
        session, user, hand, grip_type_id, edge_mm, as_of=as_of
    )
    if test is not None:
        return False

    query = (
        select(SessionMaxEstimate.training_session_id)
        .join(TrainingSession, SessionMaxEstimate.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(SessionMaxEstimate.hand == hand)
        .where(SessionMaxEstimate.grip_type_id == grip_type_id)
        .where(SessionMaxEstimate.edge_mm == edge_mm)
        .distinct()
    )
    if as_of is not None:
        query = query.where(TrainingSession.date <= as_of)
    session_ids = session.exec(query).all()
    return len(session_ids) >= ESTIMATE_NUDGE_COUNT


def session_start_nudge(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hands: list[str] | None = None,
) -> dict | None:
    """Session-start banner (ADR-0011): at most ONE banner rendered at session
    start for the combo about to be trained (retest wins if both qualify).
    Dismissible with one tap, never a modal, ephemeral (no dismissal-state table)."""
    if hands is None:
        hands = training_log.hands_for(user, None)

    retest_hands = [
        h
        for h in hands
        if retest_nudge(session, user, h, grip_type_id, edge_mm, as_of=date)
    ]
    if retest_hands:
        if len(retest_hands) == 1:
            msg = (
                f"Current max on your {retest_hands[0]} hand exceeds your last test "
                f"({RETEST_MIN_WEEKS}+ weeks ago). Time for a fresh guided test?"
            )
        else:
            msg = (
                f"Current max exceeds your last test ({RETEST_MIN_WEEKS}+ weeks ago). "
                "Time for a fresh guided test?"
            )
        return {
            "type": "retest",
            "hands": retest_hands,
            "message": msg,
        }

    estimate_hands = [
        h
        for h in hands
        if estimate_nudge(session, user, h, grip_type_id, edge_mm, as_of=date)
    ]
    if estimate_hands:
        if len(estimate_hands) == 1:
            msg = (
                f"You've estimated your {estimate_hands[0]} hand across {ESTIMATE_NUDGE_COUNT} "
                "sessions. Run a guided max test for a calibrated baseline?"
            )
        else:
            msg = (
                f"You've estimated this combination across {ESTIMATE_NUDGE_COUNT} "
                "sessions. Run a guided max test for a calibrated baseline?"
            )
        return {
            "type": "estimate",
            "hands": estimate_hands,
            "message": msg,
        }

    return None




def _combo_session_worksets(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
    before_session_id: int | None = None,
    current_session_number: int | None = None,
) -> list[list[WorkSet]]:
    """Chronologically ordered (newest first) lists of WorkSets per non-deload TrainingSession."""
    query = (
        select(TrainingSession, WorkSet)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .where(TrainingSession.is_deload.is_(False))
        .order_by(WorkSet.set_number.asc())
    )
    if before_session_id is not None:
        query = query.where(TrainingSession.id != before_session_id)
    if as_of is not None:
        query = query.where(TrainingSession.date <= as_of)

    rows = session.exec(query).all()
    session_sets: dict[tuple[date_type, int, int], list[WorkSet]] = {}
    for ts, ws in rows:
        if before_session_id is not None and ts.id == before_session_id:
            continue
        if as_of is not None and ts.date == as_of and current_session_number is not None:
            if ts.session_number >= current_session_number:
                continue
        session_sets.setdefault((ts.date, ts.session_number, ts.id or 0), []).append(ws)

    sorted_keys = sorted(session_sets.keys(), reverse=True)
    return [session_sets[k] for k in sorted_keys]


def autoregulation_trigger(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
    before_session_id: int | None = None,
    current_session_number: int | None = None,
) -> tuple[str, list[WorkSet]]:
    """Autoregulation trigger (ADR-0011, ADR-0012):
    Looks at the last AUTOREG_TRIGGER_SESSIONS (2) non-deload sessions for (hand, grip, edge).
    - If every working set in both hit target reps at RPE <= 7.0 -> "ready"
    - If any working set had RPE >= 9.0 or below target reps -> "hold"
    - If any working set had no RPE or < 2 sessions -> "ineligible"
    Returns (trigger_state, most_recent_session_worksets).
    """
    all_sessions = _combo_session_worksets(
        session, user, hand, grip_type_id, edge_mm, as_of, before_session_id, current_session_number
    )
    if len(all_sessions) < AUTOREG_TRIGGER_SESSIONS:
        return ("ineligible", [])

    recent_sessions = all_sessions[:AUTOREG_TRIGGER_SESSIONS]
    s_latest = recent_sessions[0]

    # Any missing RPE makes the session ineligible
    for worksets in recent_sessions:
        if any(ws.rpe is None for ws in worksets):
            return ("ineligible", s_latest)

    progression_settings = training_log.get_progression_settings(
        session, user, grip_type_id, edge_mm
    )

    if progression_settings.path == "double":
        # Shared trigger (ADR-0011): both recent non-deload sessions must have
        # every working set within the range (reps >= rep_min) at RPE <= 7.
        # No stabilization gate — a ready window nudges up each time; the
        # suggestion function derives which phase (rep-build vs weight-build)
        # from history.
        rep_min = progression_settings.rep_min
        for worksets in recent_sessions:
            for ws in worksets:
                if ws.rpe is None:  # unreachable: ineligibility returned above
                    continue
                if ws.rpe >= AUTOREG_RPE_HOLD_MIN or ws.reps < rep_min:
                    return ("hold", s_latest)
                if ws.rpe > AUTOREG_RPE_READY_MAX:
                    return ("hold", s_latest)

        return ("ready", s_latest)

    target_reps = progression_settings.rep_max
    all_ready = True
    for worksets in recent_sessions:
        for ws in worksets:
            if ws.rpe is None:  # unreachable: ineligibility returned above
                continue
            if ws.rpe > AUTOREG_RPE_READY_MAX or ws.reps < target_reps:
                all_ready = False

    if all_ready:
        return ("ready", s_latest)
    return ("hold", s_latest)


def autoregulation_suggestion(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    as_of: date_type | None = None,
    before_session_id: int | None = None,
    current_session_number: int | None = None,
) -> dict | None:
    """Autoregulation suggestion (ADR-0011, ADR-0012):
    When trigger is ready on Weight, Set, or Double progression path, suggests the next step."""
    state, last_worksets = autoregulation_trigger(
        session, user, hand, grip_type_id, edge_mm, as_of, before_session_id, current_session_number
    )
    if state != "ready" or not last_worksets:
        return None

    progression_settings = training_log.get_progression_settings(
        session, user, grip_type_id, edge_mm
    )
    if progression_settings.path == "weight":
        last_weight = max(ws.weight for ws in last_worksets)
        inventory = plates.inventory_for(session, user)
        ladder = plates.loadable_ladder(inventory)
        next_rung = _next_rung_above(ladder, last_weight)
        if next_rung is None:
            return None

        return {
            "hand": hand,
            "path": "weight",
            "state": "ready",
            **_weight_step_fields(user, last_weight, next_rung),
        }

    if progression_settings.path == "set":
        current_sets = len(last_worksets)
        if current_sets < progression_settings.max_sets:
            return {
                "hand": hand,
                "path": "set",
                "state": "ready",
                "current_sets": current_sets,
                "max_sets": progression_settings.max_sets,
                "message": "Ready to progress: add a set (+1 set)",
            }
        return {
            "hand": hand,
            "path": "set",
            "state": "ready",
            "current_sets": current_sets,
            "max_sets": progression_settings.max_sets,
            "message": "Ready to progress: add weight and reset to baseline sets",
        }

    if progression_settings.path == "double":
        rep_min = progression_settings.rep_min
        rep_max = progression_settings.rep_max
        last_weight = max(ws.weight for ws in last_worksets)
        last_reps = min(ws.reps for ws in last_worksets)

        if last_reps >= rep_max:
            is_weight_phase = True
        elif last_reps <= rep_min:
            is_weight_phase = False
        else:
            all_sessions = _combo_session_worksets(
                session, user, hand, grip_type_id, edge_mm, as_of, before_session_id, current_session_number
            )
            is_weight_phase = False
            for past_sets in all_sessions[2:]:
                past_weight = max(ws.weight for ws in past_sets)
                past_reps = min(ws.reps for ws in past_sets)
                if past_weight == last_weight:
                    if past_reps <= rep_min or past_reps < last_reps:
                        is_weight_phase = False
                        break
                elif past_weight < last_weight:
                    if past_reps >= rep_max:
                        is_weight_phase = True
                        break
                    elif past_reps <= rep_min:
                        is_weight_phase = False
                        break
                    # If rep_min < past_reps < rep_max, keep scanning back towards rep_max baseline

        if is_weight_phase:
            inventory = plates.inventory_for(session, user)
            ladder = plates.loadable_ladder(inventory)
            next_rung = _next_rung_above(ladder, last_weight)
            if next_rung is None:
                return None

            return {
                "hand": hand,
                "path": "double",
                "phase": "weight",
                "state": "ready",
                **_weight_step_fields(user, last_weight, next_rung),
            }
        else:
            next_reps = last_reps + 1
            return {
                "hand": hand,
                "path": "double",
                "phase": "reps",
                "state": "ready",
                "current_reps": last_reps,
                "suggested_reps": next_reps,
                "message": f"Ready to progress: try {next_reps} reps (+1 rep)",
            }

    return None


def autoregulation_suggestions(
    session: Session,
    user: User,
    grip_type_id: int,
    edge_mm: int,
    date: date_type,
    hands: list[str],
    training_session: TrainingSession | None = None,
    session_number: int | None = None,
) -> dict[str, dict | None]:
    """Evaluate autoregulation suggestions for all in-play hands."""
    before_session_id = training_session.id if training_session is not None else None
    current_sn = (
        training_session.session_number
        if training_session is not None
        else session_number
    )
    return {
        h: autoregulation_suggestion(
            session,
            user,
            h,
            grip_type_id,
            edge_mm,
            as_of=date,
            before_session_id=before_session_id,
            current_session_number=current_sn,
        )
        for h in hands
    }
