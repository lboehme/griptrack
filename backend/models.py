from datetime import date as date_type
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Fixed vocabulary for User.unit_pref -- shared by backend.auth (registration
# validation) and backend.import_restore (manifest validation, ADR-0008).
VALID_UNITS = ("kg", "lbs")


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    # Optional display name; greeting falls back to the email's local part.
    name: str | None = None
    is_admin: bool = False
    # Fixed at signup; determines the storage unit for all of this user's
    # weight values (ADR-0003: native-unit storage).
    unit_pref: str = "kg"
    # "alternating": both hands side by side per step; "sequential": one
    # hand's full flow, then the other (see HandOrderPreference in CONTEXT.md).
    hand_order_pref: str = "alternating"
    session_version: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
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
    dimension_name: str = Field(default="edge depth")


# Seeded into grip_types by the migration (prod) and the test fixture.
# Names are display names — human-readable, no underscores.
STARTER_GRIP_TYPES = [
    "half crimp",
    "full crimp",
    "open hand",
    "three finger drag",
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
    voided_at: datetime | None = None


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
    """A (user, date) can now have more than one session — e.g. a morning
    and evening pull — distinguished by session_number (see issue #51).
    session_number + date + user_id form the identity key that future
    offline sync (#20) relies on for idempotent upserts, so it must never
    be renumbered/reassigned once created. started_at is purely
    descriptive (future rest-gap analytics), never identity-bearing."""

    __tablename__ = "training_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "date", "session_number",
            name="uq_training_sessions_user_date_session_number",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    date: date_type
    session_number: int = Field(default=1)
    notes: str | None = None
    is_deload: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    # Descriptive only — not identity-bearing (see class docstring).
    started_at: datetime | None = Field(default_factory=utcnow)


class PainReport(SQLModel, table=True):
    __tablename__ = "pain_reports"
    id: int | None = Field(default=None, primary_key=True)
    training_session_id: int = Field(foreign_key="training_sessions.id", index=True)
    hand: str
    severity: int
    note: str | None = None


class WarmupStepCheck(SQLModel, table=True):
    """A ticked warmup/ramp step. Progress state only — warmup weights are
    computed, never stored (see CONTEXT.md: WorkSet)."""

    __tablename__ = "warmup_step_checks"

    id: int | None = Field(default=None, primary_key=True)
    training_session_id: int = Field(foreign_key="training_sessions.id", index=True)
    hand: str
    step_index: int


class SessionMaxEstimate(SQLModel, table=True):
    """An ephemeral, per-session stand-in for CurrentMax for a combo with no
    MaxWeightTest yet (see CONTEXT.md: SessionMaxEstimate). Scoped to one
    TrainingSession — never reused across sessions, never an analytics input."""

    __tablename__ = "session_max_estimates"
    # One row per (session, hand, grip, edge) — the upsert's invariant,
    # backed at the schema level against concurrent submissions.
    __table_args__ = (
        UniqueConstraint(
            "training_session_id", "hand", "grip_type_id", "edge_mm",
            name="uq_session_max_estimates_combo",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    training_session_id: int = Field(foreign_key="training_sessions.id", index=True)
    hand: str
    grip_type_id: int = Field(foreign_key="grip_types.id")
    edge_mm: int
    # Stored in the owning user's unit_pref (ADR-0003).
    weight: float


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


class Climb(SQLModel, table=True):
    __tablename__ = "climbs"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    date: date_type
    # "boulder" / "sport" — determines the grade scale; only boulder climbs
    # feed the strength-grade correlation (see CONTEXT.md: Discipline).
    discipline: str
    grade: str
    # Fixed vocabulary, deliberately not a lookup table: onsight / flash /
    # redpoint / attempt.
    style: str
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


CLIMB_DISCIPLINES = ("boulder", "sport")
CLIMB_STYLES = ("onsight", "flash", "redpoint", "attempt")


class Invite(SQLModel, table=True):
    __tablename__ = "invites"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    created_by_user_id: int = Field(foreign_key="users.id")
    used_by_user_id: int | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    used_at: datetime | None = None
