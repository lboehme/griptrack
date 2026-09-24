import bisect

from sqlmodel import Session, select

from backend.limits import MAX_WEIGHT
from backend.models import PlateInventoryItem, User

# Sensible starter sets; plates are denominated in the user's own unit
# (ADR-0003), so kg and lbs users get different physical defaults.
DEFAULT_INVENTORY = {
    "kg": [(0.5, 2), (1.25, 2), (2.5, 2), (5.0, 2), (10.0, 2), (20.0, 1)],
    "lbs": [(1.25, 2), (2.5, 2), (5.0, 2), (10.0, 2), (25.0, 2), (45.0, 1)],
}


def seed_default_inventory(session: Session, user: User) -> None:
    for weight, count in DEFAULT_INVENTORY[user.unit_pref]:
        session.add(PlateInventoryItem(user_id=user.id, weight=weight, count=count))
    session.commit()


def _achievable_totals_with_parents(
    inventory: list[PlateInventoryItem],
) -> tuple[set[int], dict[int, tuple[int, float]]]:
    """The single bounded subset-sum search behind both loadable_ladder and
    plate_breakdown (session play #146, issue-review item 3: "reuse the
    existing search rather than writing a second one"). Works in integer
    hundredths and caps the walk at MAX_WEIGHT, same DoS bound as before.

    Returns every achievable total (in cents), plus a `parent` map recording,
    for each total other than 0, one edge (previous_total, plate_weight)
    that first reached it -- enough to walk back and reconstruct one
    concrete combination of plates for any achievable total.
    """
    cap = int(round(MAX_WEIGHT * 100))
    achievable = {0}
    parent: dict[int, tuple[int, float]] = {}
    # Largest denomination first: loadable_ladder's achievable *set* doesn't
    # care about item order, but plate_breakdown's reconstructed combination
    # does -- biggest-plates-first is the one a person actually loading a
    # pin would reach for, and keeps the "Pin + 20 + 1.25" readout to a
    # handful of plates instead of a pile of the smallest ones.
    for item in sorted(inventory, key=lambda i: -i.weight):
        step = int(round(item.weight * 100))
        if step <= 0:
            continue
        for _ in range(item.count):
            newly_reached = {
                total + step: total
                for total in achievable
                if total + step <= cap and total + step not in achievable
            }
            for reached, prev in newly_reached.items():
                parent[reached] = (prev, item.weight)
            achievable |= newly_reached.keys()
    return achievable, parent


def loadable_ladder(inventory: list[PlateInventoryItem]) -> list[float]:
    """Every total weight the user's plates can actually make on the single
    pin (ADR-0002), ascending and deduped -- the "loadable ladder".

    An empty inventory still makes 0 (nothing loaded), so the ladder is
    never empty -- [0.0] is the defined fallback.
    """
    achievable, _ = _achievable_totals_with_parents(inventory)
    return sorted(total / 100 for total in achievable)


def plate_breakdown(
    weight: float | None, inventory: list[PlateInventoryItem]
) -> list[float] | None:
    """One concrete combination of plates (descending) that makes exactly
    `weight` on the single pin, for the "Pin + 20 + 2.5" style readout on
    the warmup rung and work-set cards (session play, #146). None when
    `weight` isn't itself on the loadable ladder (off-ladder history, a
    raw free-entry value, or simply 0) -- callers show nothing in that case,
    never a wrong or partial breakdown. A missing weight (an untested hand
    with no estimate) has no breakdown either."""
    if weight is None:
        return None
    target = int(round(weight * 100))
    if target <= 0:
        return None
    achievable, parent = _achievable_totals_with_parents(inventory)
    if target not in achievable:
        return None
    plates: list[float] = []
    node = target
    while node != 0:
        prev, plate_weight = parent[node]
        plates.append(plate_weight)
        node = prev
    plates.sort(reverse=True)
    return plates


def round_down_to_loadable(
    target_weight: float, inventory: list[PlateInventoryItem]
) -> float:
    """Closest total <= target that the user's plates can actually make.

    Consumes the shared loadable_ladder and picks the largest rung at or
    below the target. Returns 0.0 when nothing fits (empty pin, or a
    target below even the smallest -- zero -- rung).
    """
    target = int(round(target_weight * 100))
    ladder = loadable_ladder(inventory)
    cents = [int(round(rung * 100)) for rung in ladder]
    idx = bisect.bisect_right(cents, target) - 1
    if idx < 0:
        return 0.0
    return ladder[idx]


def set_plate(session: Session, user: User, weight: float, count: int) -> None:
    """Set how many plates of one denomination the user owns; 0 removes it."""
    item = session.exec(
        select(PlateInventoryItem)
        .where(PlateInventoryItem.user_id == user.id)
        .where(PlateInventoryItem.weight == weight)
    ).first()
    if count == 0:
        if item is not None:
            session.delete(item)
    elif item is None:
        session.add(PlateInventoryItem(user_id=user.id, weight=weight, count=count))
    else:
        item.count = count
        session.add(item)
    session.commit()


def inventory_for(session: Session, user: User) -> list[PlateInventoryItem]:
    return list(
        session.exec(
            select(PlateInventoryItem)
            .where(PlateInventoryItem.user_id == user.id)
            .order_by(PlateInventoryItem.weight)  # type: ignore[arg-type]  # SQLModel column typed as float, not Column
        )
    )


# Tap-to-count (Settings → Plates and first run, #151): each tap adds one
# plate; past this many it wraps back to 0 (which removes the denomination,
# like `set_plate(..., 0)`). Bigger stacks still go through the "Add a
# plate" form, which takes any count up to MAX_PLATE_COUNT.
TAP_CYCLE_MAX = 10


def tap_plate(session: Session, user: User, weight: float) -> int:
    """One tap on a plate circle: count + 1, wrapping to 0 from exactly
    TAP_CYCLE_MAX (a bigger stack is left alone). Returns the new count. Increments server-side so rapid
    taps (queued one after another by htmx) each count."""
    item = session.exec(
        select(PlateInventoryItem)
        .where(PlateInventoryItem.user_id == user.id)
        .where(PlateInventoryItem.weight == weight)
    ).first()
    current = item.count if item is not None else 0
    # Only exactly TAP_CYCLE_MAX wraps: a bigger stack (set through the
    # form) is never wiped by a stray tap -- it just stays as it is.
    if current == TAP_CYCLE_MAX:
        new_count = 0
    elif current < TAP_CYCLE_MAX:
        new_count = current + 1
    else:
        return current
    set_plate(session, user, weight, new_count)
    return new_count


def rack_view(session: Session, user: User) -> dict:
    """What the plate rack (the tap-to-count circles) shows: every plate the
    user owns plus the starter denominations for their unit at count 0, so a
    standard plate tapped down to zero stays tappable instead of vanishing;
    and the one-line "what can I load" summary off the loadable ladder."""
    inventory = inventory_for(session, user)
    counts = {item.weight: item.count for item in inventory}
    for weight, _ in DEFAULT_INVENTORY.get(user.unit_pref, []):
        counts.setdefault(weight, 0)
    owned = [item.weight for item in inventory if item.count > 0]
    return {
        "plates": [{"weight": w, "count": counts[w]} for w in sorted(counts)],
        "max_load": loadable_ladder(inventory)[-1],
        "smallest": min(owned) if owned else None,
    }
