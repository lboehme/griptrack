from datetime import date as date_type
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_admin: bool = False
    # Fixed at signup; determines the storage unit for all of this user's
    # weight values (ADR-0003: native-unit storage).
    unit_pref: str = "kg"
    # "alternating": both hands side by side per step; "sequential": one
    # hand's full flow, then the other (see HandOrderPreference in CONTEXT.md).
    hand_order_pref: str = "alternating"
    created_at: datetime = Field(default_factory=utcnow)


class BodyWeightLog(SQLModel, table=True):
    __tablename__ = "body_weight_logs"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    date: date_type
    # Stored in the owning user's unit_pref (ADR-0003).
    weight: float
    created_at: datetime = Field(default_factory=utcnow)


class PlateInventoryItem(SQLModel, table=True):
    __tablename__ = "plate_inventory_items"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    # Stored in the owning user's unit_pref (ADR-0003). One row per plate
    # denomination; the whole inventory is a single stack (ADR-0002).
    weight: float
    count: int


class Invite(SQLModel, table=True):
    __tablename__ = "invites"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    created_by_user_id: int = Field(foreign_key="users.id")
    used_by_user_id: int | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    used_at: datetime | None = None
