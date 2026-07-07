"""The guided max-test protocol (issue #21/#14): a stateless, single-hand
ladder that walks a user from a rough estimate to a real MaxWeightTest via
a fixed-weight warmup and effort-rated working sets. See CONTEXT.md.

Entirely independent of SessionMaxEstimate (issue #17) — no shared storage
or code path; the two concepts must never be confused (see #21)."""

import json

from sqlmodel import Session

from backend.limits import MAX_REPS, MAX_SET_NUMBER, MAX_WEIGHT
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


class InvalidColumn(ValueError):
    """Raised by decode_column() for a token that isn't valid ladder state —
    malformed, wrong shape, or numbers past the app's ceilings. The token is
    client-held by design (stateless routine), so decode re-validates
    everything the old field-by-field Form bounds used to."""

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


def encode_column(column: dict) -> str:
    """One hand's ladder state as a single opaque form token — the only wire
    format the two-hand routine's hidden fields carry (#22). Tokens round-trip
    through the page, so decode_column re-validates on the way back in."""
    return json.dumps(
        {key: value for key, value in column.items() if key != "token"},
        sort_keys=True,
    )


def decode_column(token: str) -> dict:
    """Parse and re-validate a ladder-state token from the page. Raises
    InvalidColumn on anything malformed or past the app's numeric ceilings."""
    try:
        column = json.loads(token)
    except (TypeError, ValueError):
        raise InvalidColumn(token)
    if not isinstance(column, dict) or column.get("hand") not in ("left", "right"):
        raise InvalidColumn(token)
    if column.get("status") == "done":
        if not _is_weight(column.get("weight")):
            raise InvalidColumn(token)
        return {"hand": column["hand"], "status": "done", "weight": column["weight"]}
    if column.get("status") != "active":
        raise InvalidColumn(token)
    valid = (
        column.get("kind") in ("warmup", "working")
        and isinstance(column.get("set_number"), int)
        and 1 <= column["set_number"] <= MAX_SET_NUMBER
        and isinstance(column.get("reps"), int)
        and 1 <= column["reps"] <= MAX_REPS
        and _is_weight(column.get("suggested"))
        and _is_weight(column.get("estimate"))
        and isinstance(column.get("needs_rating"), bool)
        and isinstance(column.get("rest_hint"), bool)
    )
    if not valid:
        raise InvalidColumn(token)
    keys = (
        "hand", "status", "kind", "set_number", "reps", "suggested",
        "needs_rating", "rest_hint", "estimate",
    )
    return {key: column[key] for key in keys}


def _is_weight(value) -> bool:
    return isinstance(value, (int, float)) and 0 < value <= MAX_WEIGHT


def start_columns(
    left_estimate: float,
    right_estimate: float,
    inventory: list[PlateInventoryItem],
) -> list[dict]:
    """Both hands' initial render state (warmup set 1) for the alternating
    routine — each ladder starts independently from its own estimate."""
    return _with_tokens(
        [
            _warmup_column("left", left_estimate, inventory),
            _warmup_column("right", right_estimate, inventory),
        ]
    )


def advance_two_hand(
    hand: str,
    kind: str,
    set_number: int,
    estimate: float,
    actual: float,
    rating: str | None,
    other_token: str,
    unit_pref: str,
    inventory: list[PlateInventoryItem],
) -> tuple[str, list[dict]]:
    """Advance one hand of the alternating routine; the other hand's state
    rides through untouched as its token. Returns (outcome, columns) with
    columns render-ready, left first — on "done" the caller records the
    active hand's MaxWeightTest with `actual`."""
    other_column = decode_column(other_token)
    outcome, step = advance(
        kind, set_number, estimate, actual, rating, unit_pref, inventory
    )
    if outcome == "done":
        this_column = {"hand": hand, "status": "done", "weight": actual}
    else:
        this_column = {"hand": hand, "status": "active", "estimate": estimate, **step}
    ordered = (
        [this_column, other_column] if hand == "left" else [other_column, this_column]
    )
    return outcome, _with_tokens(ordered)


def _with_tokens(columns: list[dict]) -> list[dict]:
    """Attach each column's own encoded token — the template embeds a
    column's token in the *other* hand's form as its echo state."""
    for column in columns:
        column["token"] = encode_column(column)
    return columns


def _warmup_column(
    hand: str, estimate: float, inventory: list[PlateInventoryItem]
) -> dict:
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
