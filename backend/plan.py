"""The per-combo training plan: sets × reps and each hand's weight for the
next session on a (grip_type, edge_mm) -- see CONTEXT.md: **Today plan**.

One derivation, two readers (PR #154 review, D1): Today's plan card
(`backend.today.build_plan`) and session play's set-1 prefill
(`backend.training_log.worksets_view`), so the weight Today shows is exactly
the weight set 1 starts at -- Go lighter's 85% included. Tapping Start is
accepting the plan; the steppers stay adjustable (ADR-0011 amendment).

Its own module because it reads both `training_log` and `analytics`, and
`training_log` needs it back (a function-local import there, the same way
`training_log` already reaches `analytics`).
"""

from dataclasses import dataclass, field
from datetime import date as date_type

from sqlmodel import Session, select

from backend import analytics, plates, training_log
from backend.models import TrainingSession, User, WorkSet

# Go lighter (CONTEXT.md: Today plan): every planned weight scaled to this,
# rounded down to the loadable ladder.
GO_LIGHTER_FACTOR = 0.85

HANDS = ("left", "right")


@dataclass
class HandPlan:
    hand: str
    weight: float | None
    # "suggestion" (autoregulation), "last" (last session), "max" (CurrentMax)
    source: str | None


@dataclass
class ComboPlan:
    sets: int
    reps: int
    hands: list[HandPlan]
    reason: str | None
    deload: bool
    default_sets: int
    # The raw autoregulation suggestions per hand (the work-set card's
    # inline hint reads these too).
    suggestions: dict = field(default_factory=dict)

    def hand(self, hand: str) -> HandPlan:
        return next(hp for hp in self.hands if hp.hand == hand)


def _fmt(weight: float) -> str:
    return f"{weight:g}"


def go_lighter_weight(weight: float, ladder: list[float]) -> float:
    """GO_LIGHTER_FACTOR of a planned weight, rounded DOWN to the loadable
    ladder (never up -- a deload must never come out heavier than 85%)."""
    target = int(round(weight * GO_LIGHTER_FACTOR * 100))
    below = [rung for rung in ladder if int(round(rung * 100)) <= target]
    return max(below) if below else 0.0


def last_session_worksets(
    session: Session,
    user: User,
    hand: str,
    grip_type_id: int,
    edge_mm: int,
    exclude_session_id: int | None,
) -> list[WorkSet]:
    """This hand's WorkSets from the most recent session on the combo,
    other than the one being planned (deloads included -- this is "what
    you did last", not a trend signal)."""
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


def _reason_phrase(suggestion: dict, unit: str, rpe: float | None) -> str:
    feel = "last session felt easy" + (f" (RPE {_fmt(rpe)})" if rpe is not None else "")
    if "suggested_weight" in suggestion:
        return f"+{_fmt(suggestion['increment'])} {unit}: {feel}"
    if "suggested_reps" in suggestion:
        return f"+1 rep: {feel}"
    if suggestion.get("path") == "set" and suggestion["current_sets"] < suggestion["max_sets"]:
        return f"+1 set: {feel}"
    return f"Ready for more weight: {feel}"


def combo_plan(
    session: Session,
    user: User,
    day: date_type,
    grip_type_id: int,
    edge_mm: int,
    training_session: TrainingSession | None,
    session_number: int | None = None,
) -> ComboPlan:
    """The plan for `training_session` (None: a session not created yet)
    on this combo: sets × reps from the TrainingProtocol and the combo's
    ProgressionPath; per-hand weight from the autoregulation suggestion
    (ADR-0011/0012), else the last session's top weight, else CurrentMax
    (or, with no test, this session's SessionMaxEstimate). Go lighter (the
    session is_deload) scales every weight to 85%, rounded down to the
    loadable ladder."""
    protocol = training_log.get_protocol(session, user)
    progression = training_log.get_progression_settings(session, user, grip_type_id, edge_mm)
    suggestions = analytics.autoregulation_suggestions(
        session, user, grip_type_id, edge_mm, day, list(HANDS),
        training_session=training_session, session_number=session_number,
    )
    exclude_id = training_session.id if training_session is not None else None
    deload = bool(training_session is not None and training_session.is_deload)
    ladder = plates.loadable_ladder(plates.inventory_for(session, user))

    lasts = {
        hand: last_session_worksets(session, user, hand, grip_type_id, edge_mm, exclude_id)
        for hand in HANDS
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
    for hand in HANDS:
        last = lasts[hand]
        suggestion = suggestions.get(hand)
        weight: float | None
        source: str | None
        if suggestion is not None and "suggested_weight" in suggestion:
            weight, source = suggestion["suggested_weight"], "suggestion"
        elif last:
            weight, source = max(ws.weight for ws in last), "last"
        else:
            weight = training_log.effective_max(
                session, user, hand, grip_type_id, edge_mm, training_session
            )
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
    return ComboPlan(
        sets=sets, reps=reps, hands=hands, reason=reason, deload=deload,
        default_sets=protocol.default_work_sets, suggestions=suggestions,
    )
