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
