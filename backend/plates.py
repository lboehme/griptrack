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


def loadable_ladder(inventory: list[PlateInventoryItem]) -> list[float]:
    """Every total weight the user's plates can actually make on the single
    pin (ADR-0002), ascending and deduped -- the "loadable ladder".

    Bounded subset-sum: work in integer hundredths to avoid float drift,
    track every achievable total, and cap the walk at MAX_WEIGHT (not at a
    per-call target) so the achievable set can never grow past a fixed size
    regardless of how large the inventory is -- this is the DoS-sensitive
    path (backend.limits). An empty inventory still makes 0 (nothing
    loaded), so the ladder is never empty -- [0.0] is the defined fallback.
    """
    cap = int(round(MAX_WEIGHT * 100))
    achievable = {0}
    for item in inventory:
        step = int(round(item.weight * 100))
        for _ in range(item.count):
            achievable |= {
                total + step for total in achievable if total + step <= cap
            }
    return sorted(total / 100 for total in achievable)


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
