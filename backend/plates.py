from sqlmodel import Session, select

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


def round_down_to_loadable(
    target_weight: float, inventory: list[PlateInventoryItem]
) -> float:
    """Closest total <= target that the user's plates can actually make.

    The inventory is a single stack on one pin (ADR-0002), so this is a
    bounded subset-sum: work in integer hundredths to avoid float drift,
    track every achievable total, and take the best one under the target.
    Returns 0.0 when nothing fits (empty pin).
    """
    target = int(round(target_weight * 100))
    achievable = {0}
    for item in inventory:
        step = int(round(item.weight * 100))
        for _ in range(item.count):
            achievable |= {
                total + step for total in achievable if total + step <= target
            }
    return max(achievable) / 100


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
            .order_by(PlateInventoryItem.weight)
        )
    )
