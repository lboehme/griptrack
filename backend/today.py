"""Today (issue #149): the coach home and the ＋ Log sheet.

One deep module behind two shallow routers (`backend.routers.home`,
`backend.routers.log_sheet`). It answers "what do I do today?" from data the
app already has -- the last-trained combo, CurrentMax, the loadable ladder,
the TrainingProtocol / ProgressionPath, the autoregulation suggestion, recent
pain reports, the plateau / overtraining heuristics -- and hides every rule
that turns those into one screen: which state Today is in (no data yet, plan,
rest day, resume, done), the plan's weights and one-line reason, the Go
lighter scaling, the week strip, and the sheet's chip defaults.

See CONTEXT.md: **Today plan** and **Rest-day suggestion**.
"""

from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta

from sqlmodel import Session, select

from backend import analytics, auth, climbing, plates, training_log
from backend.models import (
    Climb,
    GripType,
    PainReport,
    SessionMaxEstimate,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
)

# ---- tunables (see CONTEXT.md: Today plan / Rest-day suggestion) ----
GO_LIGHTER_FACTOR = 0.85
PAIN_LOOKBACK_DAYS = 7
BODYWEIGHT_STALE_DAYS = 28
REST_DAY_STREAK_DAYS = 2

# ---- ＋ Log sheet vocabulary ----
SHEET_TABS = ("climb", "bodyweight", "tweak")

# Font 5 .. 8A+, easiest first (the grade chips' full range).
FONT_GRADE_CHIPS = (
    "5", "5+", "6A", "6A+", "6B", "6B+", "6C", "6C+",
    "7A", "7A+", "7B", "7B+", "7C", "7C+", "8A", "8A+",
)
PRIMARY_GRADE_CHIPS = 10
# With no climb history the primary window is 6A..7B+ (the prototype's).
DEFAULT_GRADE_WINDOW_START = 2
RECENT_CLIMBS_FOR_DEFAULTS = 10
OTHER_GRADE = "__other__"

# (stored style, chip label). "Send" is how a redpoint reads on a chip.
STYLE_CHIPS = (
    ("flash", "Flash"),
    ("redpoint", "Send"),
    ("onsight", "Onsight"),
    ("attempt", "Attempt"),
)
DEFAULT_STYLE = "flash"

WHEN_CHOICES = ("today", "yesterday", "date")

# (severity, label, description) -- the Tweak tab's chips and the Go lighter
# card's wording for a recent pain report.
SEVERITY_CHOICES = (
    (1, "Niggle", "Noticeable, but pulling feels normal"),
    (2, "Tweak", "Pulling hurts, so I backed off"),
    (3, "Injury", "Sharp pain, I had to stop"),
)
SEVERITY_LABELS = {severity: label for severity, label, _ in SEVERITY_CHOICES}

DEFAULT_BODYWEIGHT = {"kg": 70.0, "lbs": 155.0}


class LogDateError(ValueError):
    """The ＋ Log sheet's "When" choice couldn't be resolved to a date."""


# ---------------------------------------------------------------- data shapes


@dataclass
class HandPlan:
    hand: str
    weight: float | None
    # "suggestion" (autoregulation), "last" (last session), "max" (CurrentMax)
    source: str | None


@dataclass
class TodayPlan:
    grip: GripType
    edge_mm: int
    sets: int
    reps: int
    hands: list[HandPlan]
    reason: str | None
    deload: bool
    # Passed to /session/play as `sets` only when the plan asks for more
    # than the protocol's default (Set progression's +1 set).
    sets_hint: int | None = None


@dataclass
class GoLighter:
    offered: bool
    active: bool
    headline: str | None
    detail: str | None


@dataclass
class SessionRecap:
    volume: float
    sets: int
    unit: str
    # The Summary's whole-session rating (#147); None until rated.
    session_rpe: int | None = None


@dataclass
class ResumeInfo:
    url: str
    set_number: int
    total_sets: int


@dataclass
class WeekSummary:
    sessions: int
    # No planned weekly target exists in the model yet, so this stays None
    # and the tile shows a plain count.
    target: int | None
    climbs: int
    best_send: Climb | None


@dataclass
class TodayView:
    state: str  # "no_data" | "plan" | "rest" | "resume" | "done"
    today: date_type
    greeting_name: str | None
    headline: str
    subline: str
    plan: TodayPlan | None
    go_lighter: GoLighter
    rest_reason: str | None
    resume: ResumeInfo | None
    recap: SessionRecap | None
    week: WeekSummary
    bodyweight_stale: bool
    # A second session today (done state + an explicit Change): Start pins
    # this session_number so play doesn't resolve to the finished one.
    start_session_number: int | None
    next_session_number_today: int | None
    unit: str


# ------------------------------------------------------------------ helpers


def greeting_name(user: User) -> str | None:
    """The name Today greets with: the display name, else the email's local
    part -- except the WebView build's placeholder device address, which
    must never reach the screen (ADR-0013)."""
    if user.name:
        return user.name
    if user.email == auth.DEVICE_USER_EMAIL:
        return None
    return user.email.split("@")[0]


def _fmt(weight: float) -> str:
    return f"{weight:g}"


def _session_worksets(session: Session, training_session: TrainingSession) -> list[WorkSet]:
    return list(
        session.exec(
            select(WorkSet)
            .where(WorkSet.training_session_id == training_session.id)
            .order_by(WorkSet.id)  # type: ignore[arg-type]
        ).all()
    )


def _session_has_activity(session: Session, training_session: TrainingSession) -> bool:
    """Whether a session has actually been started: a warmup tick, a work
    set, or an estimate. An empty row (created by Go lighter or a Tweak
    logged before training) doesn't turn Start into Resume."""
    for model in (WorkSet, WarmupStepCheck, SessionMaxEstimate):
        row = session.exec(
            select(model).where(model.training_session_id == training_session.id)
        ).first()
        if row is not None:
            return True
    return False


def _session_combo(
    session: Session, training_session: TrainingSession
) -> tuple[int, int] | None:
    """The (grip_type_id, edge_mm) the session's latest work set was on."""
    worksets = _session_worksets(session, training_session)
    if not worksets:
        return None
    last = worksets[-1]
    return (last.grip_type_id, last.edge_mm)


def _hands_to_check(user: User) -> list[str | None]:
    # Alternating plays both hands in one view (hand=None); sequential runs
    # each hand's flow separately, so each needs its own count.
    if user.hand_order_pref == "sequential":
        return ["left", "right"]
    return [None]


def _set_progress(
    session: Session,
    user: User,
    training_session: TrainingSession,
    combo: tuple[int, int],
) -> list[tuple[str | None, dict]]:
    """worksets_view per in-play hand -- the one place set counting lives
    (current_set_number vs. total_sets), reused rather than duplicated."""
    grip_type_id, edge_mm = combo
    return [
        (
            hand,
            training_log.worksets_view(
                session, user, grip_type_id, edge_mm, training_session.date,
                hand, None, training_session.session_number,
            ),
        )
        for hand in _hands_to_check(user)
    ]


def _session_is_done(
    session: Session, user: User, training_session: TrainingSession
) -> bool:
    """Today's "done" rule: the session was Finished on its Summary step
    (#147, `finished_at` set, even with planned sets left), or every planned
    set of the session's combo is committed (current_set_number has run past
    total_sets for every in-play hand)."""
    if training_session.finished_at is not None:
        return True
    combo = _session_combo(session, training_session)
    if combo is None:
        return False
    return all(
        view["current_set_number"] > view["total_sets"]
        for _, view in _set_progress(session, user, training_session, combo)
    )


def _resume_info(
    session: Session,
    user: User,
    training_session: TrainingSession,
    fallback_combo: tuple[int, int] | None,
) -> ResumeInfo | None:
    combo = _session_combo(session, training_session) or fallback_combo
    if combo is None:
        return None
    progress = _set_progress(session, user, training_session, combo)
    hand, view = next(
        ((h, v) for h, v in progress if v["current_set_number"] <= v["total_sets"]),
        progress[0],
    )
    url = (
        f"/session/play?grip_type_id={combo[0]}&edge_mm={combo[1]}"
        f"&date={training_session.date}&session_number={training_session.session_number}"
    )
    if hand:
        url += f"&hand={hand}"
    return ResumeInfo(url=url, set_number=view["pill_set_number"], total_sets=view["total_sets"])


def _recap(
    session: Session, user: User, training_session: TrainingSession
) -> SessionRecap:
    worksets = _session_worksets(session, training_session)
    return SessionRecap(
        volume=sum(ws.weight * ws.reps for ws in worksets),
        sets=len({(ws.grip_type_id, ws.edge_mm, ws.set_number) for ws in worksets}),
        unit=user.unit_pref,
        session_rpe=training_session.session_rpe,
    )


def _training_days(session: Session, user: User, start: date_type, end: date_type) -> set[date_type]:
    """Dates in start..end with at least one logged WorkSet (an empty
    session row isn't training)."""
    rows = session.exec(
        select(TrainingSession.date)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date >= start)
        .where(TrainingSession.date <= end)
        .distinct()
    ).all()
    return set(rows)


def _last_training_day(session: Session, user: User, before: date_type) -> date_type | None:
    return session.exec(
        select(TrainingSession.date)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date < before)
        .order_by(TrainingSession.date.desc())
    ).first()


def _sessions_in_range(session: Session, user: User, start: date_type, end: date_type) -> int:
    rows = session.exec(
        select(TrainingSession.id)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date >= start)
        .where(TrainingSession.date <= end)
        .distinct()
    ).all()
    return len(rows)


def _last_session_worksets(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    exclude_session_id: int | None,
) -> list[WorkSet]:
    """This hand's WorkSets from the most recent session on the combo,
    other than today's (deloads included -- this is "what you did last",
    not a trend signal)."""
    query = (
        select(TrainingSession, WorkSet)
        .join(WorkSet, WorkSet.training_session_id == TrainingSession.id)  # type: ignore[arg-type]
        .where(TrainingSession.user_id == user.id)
        .where(WorkSet.hand == hand)
        .where(WorkSet.grip_type_id == grip_type_id)
        .where(WorkSet.edge_mm == edge_mm)
        .order_by(
            TrainingSession.date.desc(),
            TrainingSession.session_number.desc(),
            WorkSet.set_number,  # type: ignore[arg-type]
        )
    )
    if exclude_session_id is not None:
        query = query.where(TrainingSession.id != exclude_session_id)
    rows = session.exec(query).all()
    if not rows:
        return []
    latest_id = rows[0][0].id
    return [ws for ts, ws in rows if ts.id == latest_id]


def _recent_pain(session: Session, user: User, today: date_type) -> tuple[PainReport, date_type] | None:
    row = session.exec(
        select(PainReport, TrainingSession.date)
        .join(TrainingSession, PainReport.training_session_id == TrainingSession.id)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date >= today - timedelta(days=PAIN_LOOKBACK_DAYS))
        .where(TrainingSession.date <= today)
        .order_by(TrainingSession.date.desc(), PainReport.id.desc())
    ).first()
    if row is None:
        return None
    report, report_date = row
    return report, report_date


def _combo_flags(
    session: Session, user: User, grip_type_id: int, edge_mm: int
) -> tuple[bool, bool]:
    """(plateau, overtraining) on either hand of the combo -- the same
    heuristics the dashboard pills use."""
    plateau = overtraining = False
    for hand in ("left", "right"):
        trend = analytics.training_volume_trend(session, user, hand, grip_type_id, edge_mm)
        plateau = plateau or analytics.plateau_flag(trend)
        overtraining = overtraining or analytics.overtraining_warning(trend)
    return plateau, overtraining


def go_lighter_weight(weight: float, ladder: list[float]) -> float:
    """GO_LIGHTER_FACTOR of a planned weight, rounded DOWN to the loadable
    ladder (never up -- a deload must never come out heavier than 85%)."""
    target = int(round(weight * GO_LIGHTER_FACTOR * 100))
    below = [rung for rung in ladder if int(round(rung * 100)) <= target]
    return max(below) if below else 0.0


# ---------------------------------------------------------------- the plan


def _reason_phrase(suggestion: dict, unit: str, rpe: float | None) -> str:
    feel = "last session felt easy" + (f" (RPE {_fmt(rpe)})" if rpe is not None else "")
    if "suggested_weight" in suggestion:
        return f"+{_fmt(suggestion['increment'])} {unit}: {feel}"
    if "suggested_reps" in suggestion:
        return f"+1 rep: {feel}"
    if suggestion.get("path") == "set" and suggestion["current_sets"] < suggestion["max_sets"]:
        return f"+1 set: {feel}"
    return f"Ready for more weight: {feel}"


def build_plan(
    session: Session,
    user: User,
    today: date_type,
    grip_type_id: int,
    edge_mm: int,
    today_session: TrainingSession | None,
) -> TodayPlan:
    """Today plan (CONTEXT.md): sets × reps from the TrainingProtocol and
    the combo's ProgressionPath; per-hand weight from the autoregulation
    suggestion (ADR-0011/0012), else the last session's top weight, else
    CurrentMax. Go lighter (today's session is_deload) scales every weight
    to 85%, rounded down to the loadable ladder."""
    grip = training_log.require_grip_type(session, grip_type_id)
    protocol = training_log.get_protocol(session, user)
    progression = training_log.get_progression_settings(session, user, grip_type_id, edge_mm)
    suggestions = analytics.autoregulation_suggestions(
        session, user, grip_type_id, edge_mm, today, ["left", "right"],
        training_session=today_session,
    )
    exclude_id = today_session.id if today_session is not None else None
    deload = bool(today_session is not None and today_session.is_deload)
    ladder = plates.loadable_ladder(plates.inventory_for(session, user))

    lasts = {
        hand: _last_session_worksets(session, user, hand, grip_type_id, edge_mm, exclude_id)
        for hand in ("left", "right")
    }
    had_last = any(lasts.values())

    # Sets × reps: the protocol's set count (or, on Set progression, what
    # the last session did) and the path's rep target (Double: the last
    # session's reps within the range).
    sets = protocol.default_work_sets
    if progression.path == "set" and had_last:
        sets = max(len({ws.set_number for ws in last}) for last in lasts.values())
    reps = progression.rep_max
    if progression.path == "double":
        last_reps = [min(ws.reps for ws in last) for last in lasts.values() if last]
        reps = min(last_reps) if last_reps else progression.rep_min

    hands: list[HandPlan] = []
    reasons: dict[str, str] = {}
    for hand in ("left", "right"):
        last = lasts[hand]
        suggestion = suggestions.get(hand)
        weight: float | None
        source: str | None
        if suggestion is not None and "suggested_weight" in suggestion:
            weight, source = suggestion["suggested_weight"], "suggestion"
        elif last:
            weight, source = max(ws.weight for ws in last), "last"
        else:
            weight = training_log.compute_current_max(session, user, hand, grip_type_id, edge_mm)
            source = "max" if weight is not None else None
        if suggestion is not None:
            if "suggested_reps" in suggestion:
                reps = max(reps, suggestion["suggested_reps"])
            if (
                suggestion.get("path") == "set"
                and suggestion["current_sets"] < suggestion["max_sets"]
            ):
                sets = max(sets, suggestion["current_sets"] + 1)
            rpes = [ws.rpe for ws in last if ws.rpe is not None]
            reasons[hand] = _reason_phrase(suggestion, user.unit_pref, max(rpes) if rpes else None)
        if deload and weight is not None:
            weight = go_lighter_weight(weight, ladder)
        hands.append(HandPlan(hand=hand, weight=weight, source=source))

    reason: str | None
    if deload:
        reason = f"Go lighter: {int(GO_LIGHTER_FACTOR * 100)}% of today's plan"
    elif len(reasons) == 2 and reasons["left"] == reasons["right"]:
        reason = reasons["left"]
    elif reasons:
        reason = "; ".join(f"{hand.capitalize()} {text}" for hand, text in reasons.items())
    elif had_last:
        reason = "Same as last session"
    else:
        reason = "Built from your current max"
    return TodayPlan(
        grip=grip, edge_mm=edge_mm, sets=sets, reps=reps, hands=hands,
        reason=reason, deload=deload,
        sets_hint=sets if sets > protocol.default_work_sets else None,
    )


def _go_lighter(
    session: Session,
    user: User,
    today: date_type,
    today_session: TrainingSession | None,
    plateau: bool,
    overtraining: bool,
) -> GoLighter:
    """Offered (never automatic) after a pain report in the last 7 days, or
    while the plateau or overtraining flag is on; always shown while today's
    session is already marked lighter, so it can be toggled back off."""
    active = bool(today_session is not None and today_session.is_deload)
    pain = _recent_pain(session, user, today)
    headline = detail = None
    if pain is not None:
        report, report_date = pain
        who = "Both hands" if report.hand == "both" else f"{report.hand.capitalize()} hand"
        label = SEVERITY_LABELS.get(report.severity, "Tweak").lower()
        if report_date == today:
            when = "today"
        elif report_date == today - timedelta(days=1):
            when = "yesterday"
        else:
            when = report_date.strftime("%a")
        headline = f"{who}: {label} logged {when}"
        detail = "Want to go lighter today?"
    elif overtraining:
        headline = "Big jump on short rest"
        detail = "Your last session spiked above your usual volume. Go lighter?"
    elif plateau:
        headline = "Volume has stalled on this grip"
        detail = "A lighter day can help you break through."
    offered = active or headline is not None
    if active and headline is None:
        headline = "Going lighter today"
        detail = f"Plan scaled to {int(GO_LIGHTER_FACTOR * 100)}%."
    return GoLighter(offered=offered, active=active, headline=headline, detail=detail)


def _rest_reason(
    session: Session, user: User, today: date_type, overtraining: bool
) -> str | None:
    """Rest-day suggestion (CONTEXT.md): sessions on the 2 days before today,
    or the overtraining warning on. Advisory only -- Start stays available."""
    days = _training_days(session, user, today - timedelta(days=REST_DAY_STREAK_DAYS), today - timedelta(days=1))
    if len(days) >= REST_DAY_STREAK_DAYS:
        return "You pulled two days running. Fingers recover slower than muscles."
    if overtraining:
        return "Your last session spiked above your usual volume on short rest."
    return None


def _week(session: Session, user: User, today: date_type) -> WeekSummary:
    start = today - timedelta(days=today.weekday())
    climbs = climbing.climbs_between(session, user, start, today)
    sends = [
        (analytics.parse_boulder_grade(c.grade), c)
        for c in climbs
        if c.style != "attempt" and c.discipline == "boulder"
    ]
    graded = [(value, c) for value, c in sends if value is not None]
    best = max(graded, key=lambda pair: pair[0])[1] if graded else None
    return WeekSummary(
        sessions=_sessions_in_range(session, user, start, today),
        target=None,
        climbs=len(climbs),
        best_send=best,
    )


def _bodyweight_stale(session: Session, user: User, today: date_type) -> bool:
    last = training_log.bodyweight_at(session, user)
    return last is None or (today - last.date).days > BODYWEIGHT_STALE_DAYS


def _days_ago(day: date_type, today: date_type) -> str:
    delta = (today - day).days
    if delta <= 1:
        return "You pulled yesterday."
    return f"{delta} days since your last pull."


def today_view(
    session: Session,
    user: User,
    today: date_type,
    grip_type_id: int | None = None,
    edge_mm: int | None = None,
) -> TodayView:
    """Everything the Today screen shows, in one call. `grip_type_id` /
    `edge_mm` come from the Change picker; otherwise the plan uses the
    last-trained combo (training_log.last_used_combination).

    State precedence: done > resume > no data > rest day > plan. An explicit
    Change on a done day plans a second session instead of showing the
    recap."""
    name = greeting_name(user)
    suffix = f", {name}." if name else "."
    today_session = training_log.find_session(session, user, today)
    combo: tuple[int, int] | None
    explicit = grip_type_id is not None and edge_mm is not None
    if grip_type_id is not None and edge_mm is not None:
        combo = (grip_type_id, edge_mm)
    else:
        combo = training_log.last_used_combination(session, user)
    view = TodayView(
        state="plan",
        today=today,
        greeting_name=name,
        headline="",
        subline="",
        plan=None,
        go_lighter=GoLighter(offered=False, active=False, headline=None, detail=None),
        rest_reason=None,
        resume=None,
        recap=None,
        week=_week(session, user, today),
        bodyweight_stale=_bodyweight_stale(session, user, today),
        start_session_number=None,
        next_session_number_today=today_session.session_number + 1 if today_session else None,
        unit=user.unit_pref,
    )

    if today_session is not None and _session_has_activity(session, today_session):
        if not _session_is_done(session, user, today_session):
            view.state = "resume"
            view.headline = f"Back to it{suffix}"
            view.subline = "Your session is still open. Pick up where you left off."
            view.resume = _resume_info(session, user, today_session, combo)
            return view
        if not explicit:
            view.state = "done"
            view.headline = "Done for today."
            view.subline = f"Nice work{', ' + name if name else ''}. Rest up, or log a climb."
            view.recap = _recap(session, user, today_session)
            return view
        # A second session today: plan it against a fresh session slot, not
        # the finished one (whose deload flag doesn't carry over).
        view.start_session_number = view.next_session_number_today
        today_session = None

    if combo is None:
        view.state = "no_data"
        view.headline = "One max test, then you're set."
        view.subline = (
            "Your plan is built from your max on each hand. "
            "A guided test takes about ten minutes."
        )
        return view

    combo_grip, combo_edge = combo
    view.plan = build_plan(session, user, today, combo_grip, combo_edge, today_session)
    plateau, overtraining = _combo_flags(session, user, combo_grip, combo_edge)
    view.go_lighter = _go_lighter(session, user, today, today_session, plateau, overtraining)
    if view.start_session_number is None:
        view.rest_reason = _rest_reason(session, user, today, overtraining)
    if view.rest_reason is not None:
        view.state = "rest"
        view.headline = f"Rest day{suffix}"
        view.subline = view.rest_reason
    else:
        view.state = "plan"
        view.headline = f"Pull day{suffix}"
        last_day = _last_training_day(session, user, today)
        view.subline = (
            _days_ago(last_day, today) if last_day else "First session on the board. Start easy."
        )
    return view


def set_go_lighter(
    session: Session, user: User, date: date_type, on: bool
) -> TrainingSession:
    """Toggle Go lighter: marks today's session is_deload (creating the
    session under the usual start_or_get_session rules if needed). Never
    automatic -- only this explicit toggle writes the flag."""
    training_session = training_log.start_or_get_session(session, user, date)
    training_session.is_deload = on
    session.add(training_session)
    session.commit()
    session.refresh(training_session)
    return training_session


def picker_view(
    session: Session, user: User, grip_type_id: int | None, edge_mm: int | None
) -> dict:
    """The Change picker (replaces /session/new's form): grip + edge,
    preselected to the current plan's combo (else the last-trained one)."""
    if grip_type_id is None or edge_mm is None:
        last = training_log.last_used_combination(session, user)
        if last is not None:
            grip_type_id, edge_mm = last
    return {
        "grip_types": session.exec(select(GripType).order_by(GripType.name)).all(),
        "selected_grip_type_id": grip_type_id,
        "selected_edge_mm": edge_mm,
    }


# ------------------------------------------------------------- ＋ Log sheet


def grade_chips(session: Session, user: User) -> tuple[list[str], list[str]]:
    """(primary, rest): the 10 Font grades closest to the user's recent
    grades first (a contiguous window around their median), the remainder
    after -- scrollable in the sheet."""
    values = sorted(
        v
        for v in (
            analytics.parse_boulder_grade(c.grade)
            for c in climbing.recent_climbs(session, user, RECENT_CLIMBS_FOR_DEFAULTS)
        )
        if v is not None
    )
    start = DEFAULT_GRADE_WINDOW_START
    if values:
        median = values[len(values) // 2]
        chip_values = [analytics.FONT_TO_V[g] for g in FONT_GRADE_CHIPS]
        center = min(range(len(chip_values)), key=lambda i: (abs(chip_values[i] - median), -i))
        start = center - PRIMARY_GRADE_CHIPS // 2 + 1
    start = max(0, min(start, len(FONT_GRADE_CHIPS) - PRIMARY_GRADE_CHIPS))
    primary = list(FONT_GRADE_CHIPS[start:start + PRIMARY_GRADE_CHIPS])
    rest = [g for g in FONT_GRADE_CHIPS if g not in primary]
    return primary, rest


def sheet_view(session: Session, user: User, tab: str, today: date_type) -> dict:
    """Everything the ＋ Log sheet renders for one tab."""
    if tab not in SHEET_TABS:
        tab = "climb"
    view: dict = {"tab": tab, "today": today, "unit": user.unit_pref}
    if tab == "climb":
        primary, rest = grade_chips(session, user)
        recent = climbing.recent_climbs(session, user, 1)
        view.update(
            primary_grades=primary,
            more_grades=rest,
            styles=STYLE_CHIPS,
            default_style=recent[0].style if recent and recent[0].style in dict(STYLE_CHIPS) else DEFAULT_STYLE,
            other_grade=OTHER_GRADE,
        )
    elif tab == "bodyweight":
        last = training_log.bodyweight_at(session, user)
        view.update(
            bodyweight=last.weight if last else DEFAULT_BODYWEIGHT.get(user.unit_pref, 70.0),
            last_bodyweight=last,
        )
    else:
        view.update(
            hands=training_log.PAIN_REPORT_HANDS,
            severities=SEVERITY_CHOICES,
        )
    return view


def resolve_climb_grade(grade: str, grade_other: str | None) -> str:
    """The chip's grade, or the Other… text when that chip was picked."""
    if grade == OTHER_GRADE:
        text = (grade_other or "").strip()
        if not text:
            raise ValueError("Type a grade for Other…")
        return text
    return grade.strip()


def resolve_log_date(when: str, client_today: date_type, pick_date: date_type | None) -> date_type:
    """The sheet's When chips: Today / Yesterday are relative to the
    client-local date the page submitted (client-date.js); a picked date is
    taken as-is."""
    if when == "today":
        return client_today
    if when == "yesterday":
        return client_today - timedelta(days=1)
    if when == "date":
        if pick_date is None:
            raise LogDateError("Pick a date.")
        return pick_date
    raise LogDateError("When must be today, yesterday, or a date.")


def log_tweak(
    session: Session,
    user: User,
    date: date_type,
    hand: str,
    severity: int,
    note: str | None,
) -> PainReport:
    """The Tweak tab: a PainReport on the day's session, creating the session
    under the existing rules -- today creates implicitly, but a past date
    with no session is refused (the explicit past-session-creation gate)."""
    if hand not in training_log.PAIN_REPORT_HANDS:
        raise ValueError("Hand must be left, right, or both.")
    if severity not in SEVERITY_LABELS:
        raise ValueError("Severity must be 1, 2, or 3.")
    existing = training_log.find_session(session, user, date)
    if existing is None and training_log.is_past_date(date):
        raise LogDateError("No session on that date.")
    training_session = existing or training_log.start_or_get_session(session, user, date)
    return training_log.record_pain_report(
        session, training_session, hand, severity, (note or "").strip() or None
    )


# Toast text after a sheet save, keyed by tab. The `saved=` flag that rides
# the no-JS POST-redirect-GET selects one of these server-side constants; the
# query string is never echoed.
SAVED_MESSAGES = {
    "climb": "Climb logged",
    "bodyweight": "Bodyweight logged",
    "tweak": "Tweak noted",
}
