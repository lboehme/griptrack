"""Progress (#150): "am I getting stronger, and does it show in my climbing?"

Three layers, all assembled here so the router stays a thin adapter:

1. **Story sentences** -- fixed-template sentences over the EXISTING
   analytics signals (never a new statistic), each shown only when its
   signal passes that signal's own threshold (`story_sentences`).
2. **The headline chart** -- CurrentMax as % of bodyweight per hand, with
   boulder sends on a grade axis (`analytics.strength_pct_bodyweight_series`
   plus the send dots, shipped as JSON-in-DOM for uPlot).
3. **Go deeper** -- detail pages whose content moved unchanged from the old
   Trends, History and Max tests pages; the timeline (`timeline_view`) is
   the one new list among them.
"""

from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta

from sqlmodel import Session, select

from backend import analytics, climbing, training_log
from backend.models import GripType, SessionMaxEstimate, TrainingSession, User
from backend.templating import human_date

# Range picker (6W / 3M / All). `days` None means the whole history.
RANGES: dict[str, dict] = {
    "6w": {"label": "6W", "days": 42, "span": "in 6 weeks", "phrase": "the last 6 weeks"},
    "3m": {"label": "3M", "days": 91, "span": "in 3 months", "phrase": "the last 3 months"},
    "all": {"label": "All", "days": None, "span": None, "phrase": "all time"},
}
DEFAULT_RANGE = "6w"
MAX_STORY_SENTENCES = 3

# Correlation-in-words buckets on |rho| (wording only -- the n >= 8 floor
# and zero-variance rules stay in analytics.strength_grade_correlation).
CORRELATION_WORDS = ((0.7, "strong"), (0.4, "moderate"), (0.2, "weak"))

HANDS = ("left", "right")


@dataclass
class Sentence:
    """One story sentence: a bold claim, then muted advice (V10)."""

    kind: str
    claim: str
    advice: str = ""
    hand: str | None = None


@dataclass
class Combo:
    grip_type_id: int
    edge_mm: int
    grip_name: str
    dimension_name: str
    selected: bool = False
    query: str = ""


@dataclass
class HandLegend:
    hand: str
    latest_pct: float | None


@dataclass
class ProgressView:
    combos: list[Combo]
    combo: Combo | None
    range_key: str
    ranges: list[dict]
    chart: dict
    legend: list[HandLegend]
    grade_bands: list[dict]
    sentences: list[Sentence]
    aria_label: str
    has_points: bool = False


def _hand_name(hand: str) -> str:
    return hand.capitalize()


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def data_combos(session: Session, user: User) -> list[Combo]:
    """Every (grip, edge) with a WorkSet or a non-voided MaxWeightTest on
    either hand -- the combo picker's choices."""
    seen: dict[tuple[int, int], Combo] = {}
    for c in training_log.trained_combinations(session, user):
        key = (c["grip_type_id"], c["edge_mm"])
        if key not in seen:
            seen[key] = Combo(
                grip_type_id=c["grip_type_id"],
                edge_mm=c["edge_mm"],
                grip_name=c["grip_name"],
                dimension_name=c["dimension_name"],
            )
    return sorted(seen.values(), key=lambda c: (c.grip_name, c.edge_mm))


def range_start(range_key: str, today: date_type) -> date_type | None:
    days = RANGES[range_key]["days"]
    return None if days is None else today - timedelta(days=days)


def _query(grip_type_id: int | None, edge_mm: int | None, range_key: str) -> str:
    parts = []
    if grip_type_id is not None and edge_mm is not None:
        parts.append(f"grip_type_id={grip_type_id}&edge_mm={edge_mm}")
    parts.append(f"range={range_key}")
    return "&".join(parts)


# ------------------------------------------------------------ story layer


def _change_sentence(
    hand: str, points: list[tuple[date_type, float]], range_key: str
) -> Sentence | None:
    """%BW change over the range for one hand: only if it moved (rounded to
    a whole percent), and only with two or more points to compare."""
    if len(points) < 2:
        return None
    first_date, first = points[0]
    _last_date, last = points[-1]
    if first <= 0:
        return None
    change = round((last - first) / first * 100)
    if change == 0:
        return None
    direction = "up" if change > 0 else "down"
    span = RANGES[range_key]["span"] or f"since {human_date(first_date)}"
    return Sentence(
        kind="change",
        hand=hand,
        claim=f"{_hand_name(hand)} {direction} {abs(change)}% {span}.",
        advice=f"{_pct(last)} of bodyweight now.",
    )


def _held_for(trend: list[tuple[date_type, float]]) -> str:
    """How long a plateaued trend has held: from the earlier best that the
    recent sessions never beat (plateau_flag's own comparison) to the
    latest session -- in weeks once that's two weeks or more, otherwise in
    sessions."""
    earlier = trend[: -analytics.PLATEAU_RECENT_SESSIONS]
    best = max(volume for _, volume in earlier)
    best_index = max(i for i, (_, volume) in enumerate(earlier) if volume == best)
    days = (trend[-1][0] - trend[best_index][0]).days
    if days >= 14:
        return f"{days // 7} weeks"
    sessions = len(trend) - 1 - best_index
    return f"{sessions} sessions"


def _correlation_sentence(correlation: dict) -> Sentence | None:
    r = correlation["r"]
    if r is None:
        return None
    n = correlation["n"]
    strength = next((word for floor, word in CORRELATION_WORDS if abs(r) >= floor), None)
    if strength is None:
        return Sentence(
            kind="correlation",
            claim="No clear link yet between strength and grade.",
            advice=f"Across {n} boulder sends, your grades haven't tracked your pull.",
        )
    if r > 0:
        return Sentence(
            kind="correlation",
            claim="Your sends are following.",
            advice=f"Across {n} boulder sends, harder grades came with a stronger pull ({strength} link).",
        )
    return Sentence(
        kind="correlation",
        claim="Your sends aren't following yet.",
        advice=f"Across {n} boulder sends, grade and strength moved in opposite directions ({strength} link).",
    )


def _missing_sentence(
    session: Session, user: User, combo: Combo | None, correlation: dict
) -> Sentence | None:
    """The single "what's missing" line for thin data, most basic gap
    first. Counts never go negative (#138)."""
    if combo is None:
        return Sentence(
            kind="missing",
            claim="Nothing to chart yet.",
            advice="Run a max test to start your strength line.",
        )
    if training_log.bodyweight_at(session, user) is None:
        return Sentence(
            kind="missing",
            claim="Log your bodyweight",
            advice="to see strength as a share of it.",
        )
    if correlation["r"] is None and correlation["n"] < analytics.CORRELATION_MIN_POINTS:
        remaining = max(0, analytics.CORRELATION_MIN_POINTS - correlation["n"])
        noun = "send" if remaining == 1 else "sends"
        return Sentence(
            kind="missing",
            claim=f"Log {remaining} more boulder {noun}",
            advice="to see how strength tracks grade.",
        )
    return None


def story_sentences(
    session: Session,
    user: User,
    combo: Combo | None,
    range_key: str,
    series: dict[str, list[tuple[date_type, float]]],
) -> list[Sentence]:
    """Progress's headline sentences, in priority order, at most
    MAX_STORY_SENTENCES. Every sentence is a fixed template over an
    existing analytics signal and appears only when that signal passes its
    existing threshold:

    1. CurrentMax %BW change over the range, per hand (only if it moved).
    2. analytics.plateau_flag on the hand's TrainingVolume trend.
    3. analytics.overtraining_warning on the same trend.
    4. analytics.asymmetry_warning on the combo's load-gap trend (ADR-0010).
    5. analytics.strength_grade_correlation's rho (n >= 8 floor), in words.

    With room left, one "what's missing" line explains the thinnest gap."""
    sentences: list[Sentence] = []
    correlation = analytics.strength_grade_correlation(session, user)

    if combo is not None:
        for hand in HANDS:
            sentence = _change_sentence(hand, series.get(hand, []), range_key)
            if sentence is not None:
                sentences.append(sentence)

        trends = {
            hand: analytics.training_volume_trend(
                session, user, hand, combo.grip_type_id, combo.edge_mm
            )
            for hand in HANDS
        }
        for hand in HANDS:
            if analytics.plateau_flag(trends[hand]):
                sentences.append(
                    Sentence(
                        kind="plateau",
                        hand=hand,
                        claim=f"{_hand_name(hand)} has held for {_held_for(trends[hand])}.",
                        advice="A deload or a retest could break it.",
                    )
                )
        for hand in HANDS:
            if analytics.overtraining_warning(trends[hand]):
                sentences.append(
                    Sentence(
                        kind="overtraining",
                        hand=hand,
                        claim=f"{_hand_name(hand)} spiked after a short rest.",
                        advice="Volume jumped while the rest before it was shorter than usual. Go easy next time.",
                    )
                )

        load_gaps = analytics.load_gap_trend(session, user, combo.grip_type_id, combo.edge_mm)
        if analytics.asymmetry_warning(load_gaps):
            latest_gap = load_gaps[-1][1]
            heavier = "Left" if latest_gap > 0 else "Right"
            sentences.append(
                Sentence(
                    kind="asymmetry",
                    claim="Your hands are drifting apart.",
                    advice=f"{heavier} is carrying more load than your usual balance.",
                )
            )

    correlation_sentence = _correlation_sentence(correlation)
    if correlation_sentence is not None:
        sentences.append(correlation_sentence)

    sentences = sentences[:MAX_STORY_SENTENCES]
    if len(sentences) < MAX_STORY_SENTENCES:
        missing = _missing_sentence(session, user, combo, correlation)
        if missing is not None:
            sentences.append(missing)
    return sentences


# ------------------------------------------------------------ chart layer


def _sends(session: Session, user: User, since: date_type | None) -> list[dict]:
    """Boulder sends with a parseable grade (the correlation's own filter),
    oldest first, for the chart's grade axis."""
    sends = []
    for climb in reversed(climbing.climbs_newest_first(session, user)):
        if climb.discipline != "boulder":
            continue
        if since is not None and climb.date < since:
            continue
        value = analytics.parse_boulder_grade(climb.grade)
        if value is None:
            continue
        sends.append(
            {
                "date": climb.date.isoformat(),
                "grade": climb.grade,
                "value": value,
                "token": climbing.grade_color_token(climb.grade) or "--mu",
            }
        )
    return sends


def _grade_bands(sends: list[dict]) -> list[dict]:
    """The grade legend below the chart: one entry per colour band that
    actually appears, easiest first, labelled with the grades seen."""
    bands: dict[str, list[str]] = {}
    order: dict[str, float] = {}
    for send in sorted(sends, key=lambda s: s["value"]):
        grades = bands.setdefault(send["token"], [])
        order.setdefault(send["token"], send["value"])
        if send["grade"] not in grades:
            grades.append(send["grade"])
    return [
        {"token": token, "label": grades[0] if len(grades) == 1 else f"{grades[0]}–{grades[-1]}"}
        for token, grades in sorted(bands.items(), key=lambda item: order[item[0]])
    ]


def progress_view(
    session: Session,
    user: User,
    today: date_type,
    grip_type_id: int | None,
    edge_mm: int | None,
    range_key: str,
) -> ProgressView:
    """Everything /progress renders. The combo defaults to the last trained
    (or tested) one; an explicit (grip, edge) wins even with no data yet."""
    combos = data_combos(session, user)
    if grip_type_id is not None and edge_mm is not None:
        chosen: tuple[int, int] | None = (grip_type_id, edge_mm)
    else:
        chosen = training_log.last_used_combination(session, user)

    combo: Combo | None = None
    if chosen is not None:
        combo = next(
            (c for c in combos if (c.grip_type_id, c.edge_mm) == chosen), None
        )
        if combo is None:
            grip = training_log.require_grip_type(session, chosen[0])
            combo = Combo(
                grip_type_id=chosen[0],
                edge_mm=chosen[1],
                grip_name=grip.name,
                dimension_name=grip.dimension_name,
            )
        combo.selected = True
    for c in combos:
        c.query = _query(c.grip_type_id, c.edge_mm, range_key)

    since = range_start(range_key, today)
    series: dict[str, list[tuple[date_type, float]]] = {hand: [] for hand in HANDS}
    if combo is not None:
        series = analytics.strength_pct_bodyweight_series(
            session, user, combo.grip_type_id, combo.edge_mm, since=since
        )
    sends = _sends(session, user, since)

    chart = {
        "since": since.isoformat() if since is not None else None,
        "today": today.isoformat(),
        "hands": {
            hand: {
                "dates": [d.isoformat() for d, _ in series[hand]],
                "values": [v for _, v in series[hand]],
            }
            for hand in HANDS
        },
        "sends": sends,
    }
    legend = [
        HandLegend(hand=hand, latest_pct=series[hand][-1][1] if series[hand] else None)
        for hand in HANDS
    ]

    combo_text = (
        f"{combo.grip_name.capitalize()} {combo.edge_mm} mm" if combo is not None else "no combo"
    )
    latest_text = ", ".join(
        f"{_hand_name(entry.hand)} {_pct(entry.latest_pct)}"
        for entry in legend
        if entry.latest_pct is not None
    )
    aria_label = (
        f"Strength as % of bodyweight, {combo_text}, {RANGES[range_key]['phrase']}"
        + (f": {latest_text}" if latest_text else ": no data yet")
        + (f", with {len(sends)} boulder sends by grade." if sends else ".")
    )

    return ProgressView(
        combos=combos,
        combo=combo,
        range_key=range_key,
        ranges=[
            {
                "key": key,
                "label": spec["label"],
                "selected": key == range_key,
                "query": _query(
                    combo.grip_type_id if combo else None,
                    combo.edge_mm if combo else None,
                    key,
                ),
            }
            for key, spec in RANGES.items()
        ],
        chart=chart,
        legend=legend,
        grade_bands=_grade_bands(sends),
        sentences=story_sentences(session, user, combo, range_key, series),
        aria_label=aria_label,
        has_points=any(series[hand] for hand in HANDS) or bool(sends),
    )


# ------------------------------------------------------------ timeline


def _session_combo(
    session: Session, training_session: TrainingSession, work_sets: list
) -> tuple[int, int] | None:
    """The combo a timeline row opens in /session/play: the session's first
    work set's (by set number), else a SessionMaxEstimate's, else none
    (a session with only warmup ticks has no combo on record)."""
    if work_sets:
        first = work_sets[0]
        return first.grip_type_id, first.edge_mm
    estimate = session.exec(
        select(SessionMaxEstimate)
        .where(SessionMaxEstimate.training_session_id == training_session.id)
        .order_by(SessionMaxEstimate.id)  # type: ignore[arg-type]
    ).first()
    if estimate is not None:
        return estimate.grip_type_id, estimate.edge_mm
    return None


def _week_start(day: date_type) -> date_type:
    return day - timedelta(days=day.weekday())


def timeline_view(
    session: Session, user: User, today: date_type, climbs_only: bool = False
) -> list[dict]:
    """All sessions and climbs, newest first, grouped by (Monday-starting)
    week. Session rows carry their combo, top set, volume (Σ weight × reps
    across the session), Session RPE and deload flag, plus the
    /session/play link that reopens them (finished sessions land on their
    summary step)."""
    names = training_log.grip_names(session)
    dimensions = training_log.grip_dimension_names(session)
    entries: list[dict] = []

    if not climbs_only:
        for item in training_log.session_history(session, user):
            ts = item["session"]
            work_sets = list(item["work_sets"])
            combo = _session_combo(session, ts, work_sets)
            combos = []
            for ws in work_sets:
                key = (ws.grip_type_id, ws.edge_mm)
                if key not in combos:
                    combos.append(key)
            top = max(work_sets, key=lambda ws: (ws.weight, ws.reps)) if work_sets else None
            href = None
            if combo is not None:
                href = (
                    f"/session/play?grip_type_id={combo[0]}&edge_mm={combo[1]}"
                    f"&date={ts.date.isoformat()}&session_number={ts.session_number}"
                )
            entries.append(
                {
                    "kind": "session",
                    "date": ts.date,
                    "order": (0, -ts.session_number),
                    "session": ts,
                    "work_sets": work_sets,
                    "grip_name": names.get(combo[0], "") if combo else "",
                    "dimension_name": dimensions.get(combo[0], "") if combo else "",
                    "edge_mm": combo[1] if combo else None,
                    "more_combos": max(0, len(combos) - 1),
                    "top": top,
                    "volume": sum(ws.weight * ws.reps for ws in work_sets),
                    "href": href,
                }
            )

    for climb in climbing.climbs_newest_first(session, user):
        entries.append(
            {
                "kind": "climb",
                "date": climb.date,
                "order": (1, 0),
                "climb": climb,
            }
        )

    # Stable sort: within a date, sessions (latest session_number first)
    # precede climbs; climbs keep their newest-first order.
    entries.sort(key=lambda e: e["order"])
    entries.sort(key=lambda e: e["date"], reverse=True)

    this_week = _week_start(today)
    weeks: list[dict] = []
    for entry in entries:
        start = _week_start(entry["date"])
        if not weeks or weeks[-1]["start"] != start:
            if start == this_week:
                label = "This week"
            elif start == this_week - timedelta(days=7):
                label = "Last week"
            else:
                label = None
            weeks.append({"start": start, "label": label, "entries": []})
        weeks[-1]["entries"].append(entry)
    return weeks


# ------------------------------------------------------------ maxes


def maxes_view(session: Session, user: User) -> dict:
    """The Maxes detail page (moved unchanged from /max-tests)."""
    return {
        "grip_types": session.exec(select(GripType).order_by(GripType.name)).all(),
        "combos": training_log.tested_combinations(session, user),
        "test_history": training_log.max_test_history(session, user),
    }
