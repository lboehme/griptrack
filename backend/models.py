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


class GripType(SQLModel, table=True):
    __tablename__ = "grip_types"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)


# Seeded into grip_types by the migration (prod) and the test fixture.
STARTER_GRIP_TYPES = [
    "half_crimp",
    "full_crimp",
    "open_hand",
    "three_finger_drag",
    "pinch",
]


class MaxWeightTest(SQLModel, table=True):
    __tablename__ = "max_weight_tests"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    hand: str  # "left" / "right"
    grip_type_id: int = Field(foreign_key="grip_types.id")
    edge_mm: int
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


class TrainingProtocol(SQLModel, table=True):
    __tablename__ = "training_protocols"

    id: int | None = Field(default=None, primary_key=True)
    # NULL user_id = the single global default row (ADR-0005); per-user
    # overrides become possible later without a schema rework.
    user_id: int | None = Field(default=None, foreign_key="users.id")
    ramp_percentages: str = "50,65,80,90"
    base_work_set_reps: int = 5
    default_work_sets: int = 3


class TrainingSession(SQLModel, table=True):
    __tablename__ = "training_sessions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    date: date_type
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class WarmupStepCheck(SQLModel, table=True):
    """A ticked warmup/ramp step. Progress state only — warmup weights are
    computed, never stored (see CONTEXT.md: WorkSet)."""

    __tablename__ = "warmup_step_checks"

    id: int | None = Field(default=None, primary_key=True)
    training_session_id: int = Field(foreign_key="training_sessions.id", index=True)
    hand: str
    step_index: int


class WorkSet(SQLModel, table=True):
    __tablename__ = "work_sets"

    id: int | None = Field(default=None, primary_key=True)
    training_session_id: int = Field(foreign_key="training_sessions.id", index=True)
    hand: str
    grip_type_id: int = Field(foreign_key="grip_types.id")
    edge_mm: int
    # Stored in the owning user's unit_pref (ADR-0003).
    weight: float
    reps: int
    set_number: int
    # 1.0-10.0 in 0.5 increments, optional (see CONTEXT.md: RPE).
    rpe: float | None = None


class Invite(SQLModel, table=True):
    __tablename__ = "invites"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    created_by_user_id: int = Field(foreign_key="users.id")
    used_by_user_id: int | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    used_at: datetime | None = None
