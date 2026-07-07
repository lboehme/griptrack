"""The guided max-test protocol (issue #21/#14): a stateless, single-hand
ladder that walks a user from a rough estimate to a real MaxWeightTest via
a fixed-weight warmup and effort-rated working sets. See CONTEXT.md.

Entirely independent of SessionMaxEstimate (issue #17) — no shared storage
or code path; the two concepts must never be confused (see #21)."""

from sqlmodel import Session

from backend.models import PlateInventoryItem, User
from backend.plates import round_down_to_loadable
from backend.training_log import bodyweight_at

WARMUP_PERCENT = 50
WARMUP_REPS = 8
WORKING_REPS = 3

# Effort-increment ladder driving the next suggested weight, expressed per
# unit_pref (never converted between units — mirrors ADR-0003's native-unit
# precedent) rather than a raw kg<->lbs conversion of one master table.
LADDERS = {
    "kg": {"effortless": 10, "fairly_easy": 5, "moderate": 2, "hard": 1},
    "lbs": {"effortless": 20, "fairly_easy": 10, "moderate": 5, "hard": 2.5},
}

# A rating on the set just finished, not the one about to start: the set
# that follows a Moderate/Hard rating gets the rest-hint.
REST_HINT_RATINGS = {"moderate", "hard"}

RATING_VALUES = {"effortless", "fairly_easy", "moderate", "hard", "enough"}


class InvalidRating(ValueError):
    """Raised by advance() for a missing or unrecognized rating — the only
    step allowed to omit one is warmup set 1."""

# A starting-estimate suggestion for a user who has no idea what to enter:
# up to half of bodyweight is already a solid block-pull max for most
# lifters (e.g. 80kg bodyweight -> 40kg estimate). With no BodyWeightLog on
# file at all, fall back to a flat, conservative per-unit default.
BODYWEIGHT_ESTIMATE_FRACTION = 0.5
FALLBACK_ESTIMATE = {"kg": 10.0, "lbs": 20.0}


def default_estimate(session: Session, user: User) -> float:
    bodyweight = bodyweight_at(session, user)
    if bodyweight is not None:
        return round(bodyweight.weight * BODYWEIGHT_ESTIMATE_FRACTION, 2)
    return FALLBACK_ESTIMATE[user.unit_pref]


def warmup_suggestion(
    estimate: float, inventory: list[PlateInventoryItem]
) -> float:
    """Both warmup sets target the same weight: 50% of the entered
    estimate, plate-rounded as guidance — never chained off each other."""
    return round_down_to_loadable(estimate * WARMUP_PERCENT / 100, inventory)


def done_column(hand: str, weight: float) -> dict:
    """A hand that already recorded its MaxWeightTest in this routine run —
    the two-hand template shows this as a plain notice, not a live form."""
    return {"hand": hand, "status": "done", "weight": weight}


def active_column(
    hand: str,
    kind: str,
    set_number: int,
    reps: int,
    suggested: float,
    needs_rating: bool,
    rest_hint: bool,
    estimate: float,
) -> dict:
    """A hand still mid-ladder — either the hand just advanced by this
    request, or the other hand's state, echoed back unchanged."""
    return {
        "hand": hand,
        "status": "active",
        "kind": kind,
        "set_number": set_number,
        "reps": reps,
        "suggested": suggested,
        "needs_rating": needs_rating,
        "rest_hint": rest_hint,
        "estimate": estimate,
    }


def ordered_columns(hand: str, this_column: dict, other_column: dict) -> list[dict]:
    """Left/right in a stable, predictable order regardless of which hand's
    form was just submitted — the two-hand template always renders left
    before right."""
    return [this_column, other_column] if hand == "left" else [other_column, this_column]


def warmup_column(hand: str, estimate: float, inventory: list[PlateInventoryItem]) -> dict:
    """A hand's initial rendered state (warmup set 1) for the two-hand
    alternating routine (#22) — each hand's ladder starts independently
    from its own entered estimate."""
    return {
        "hand": hand,
        "status": "active",
        "kind": "warmup",
        "set_number": 1,
        "reps": WARMUP_REPS,
        "suggested": warmup_suggestion(estimate, inventory),
        "needs_rating": False,
        "rest_hint": False,
        "estimate": estimate,
    }


def advance(
    kind: str,
    set_number: int,
    estimate: float,
    actual: float,
    rating: str | None,
    unit_pref: str,
    inventory: list[PlateInventoryItem],
) -> tuple[str, dict | None]:
    """The single state-transition entry point for a confirmed set.

    Validates the rating for this step (only warmup set 1 may omit one —
    every later step requires it, or a missing rating would otherwise be
    mistaken for that one no-rating transition) and returns either
    ("done", None) — the caller should record a MaxWeightTest with `actual`
    — or ("step", <next step dict>). Raises InvalidRating otherwise."""
    if rating is not None and rating not in RATING_VALUES:
        raise InvalidRating(rating)
    first_warmup_set = kind == "warmup" and set_number == 1
    if rating is None and not first_warmup_set:
        raise InvalidRating(rating)
    if rating == "enough":
        return "done", None
    return "step", _next_step(
        kind, set_number, estimate, actual, rating, unit_pref, inventory
    )


def _next_step(
    kind: str,
    set_number: int,
    estimate: float,
    actual: float,
    rating: str | None,
    unit_pref: str,
    inventory: list[PlateInventoryItem],
) -> dict:
    """The rendered step after a set is confirmed. Warmup set 1 collects no
    rating (both warmup sets are fixed at the same weight, so it just
    repeats the 50%-of-estimate suggestion); every other step's rating
    drives the next suggestion via the increment ladder off the
    just-confirmed actual — never the suggestion that was shown."""
    if rating is None:
        return {
            "kind": "warmup",
            "set_number": 2,
            "reps": WARMUP_REPS,
            "suggested": warmup_suggestion(estimate, inventory),
            "needs_rating": True,
            "rest_hint": False,
        }
    increment = LADDERS[unit_pref][rating]
    return {
        "kind": "working",
        "set_number": 1 if kind == "warmup" else set_number + 1,
        "reps": WORKING_REPS,
        "suggested": round_down_to_loadable(actual + increment, inventory),
        "needs_rating": True,
        "rest_hint": rating in REST_HINT_RATINGS,
    }
