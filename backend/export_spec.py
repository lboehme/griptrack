"""Shared spec for the versioned export/import archive (ADR-0008, #100).

One definition of which models `GET /profile/export` writes into the
archive, their weight-bearing columns (so the exporter can stamp a
`(kg)`/`(lbs)` header suffix per ADR-0003 native-unit storage), and how each
model is scoped to a user. Both the exporter
(`backend.routers.profile.export_data`) and the future importer (#102) read
this one list so the two directions of the round trip can't drift apart.

Bumping `FORMAT_VERSION` is a breaking archive-contract change (ADR-0008):
import is expected to reject any archive whose manifest doesn't carry a
`format_version` it recognizes.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlmodel import SQLModel, select
from sqlmodel.sql.expression import SelectOfScalar

from backend.models import (
    BodyWeightLog,
    Climb,
    GripType,
    MaxWeightTest,
    PainReport,
    PlateInventoryItem,
    SessionMaxEstimate,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
)

FORMAT_VERSION = 1
MANIFEST_FILENAME = "manifest.json"


class Scope(Enum):
    """How a member's rows are scoped to a user for export/import."""

    # No user link at all -- shared reference data. Every row goes into
    # every archive, unfiltered. GripType is the only current member.
    GLOBAL = "global"
    # Direct user_id foreign key.
    USER = "user"
    # Indirect: scoped via training_session_id -> TrainingSession.user_id.
    # Callers must supply the user's TrainingSession ids explicitly (see
    # `scoped_query`) -- this spec doesn't do the join itself.
    TRAINING_SESSION = "training_session"


@dataclass(frozen=True)
class ArchiveMember:
    """One CSV member of the export/import archive."""

    model: type[SQLModel]
    scope: Scope = Scope.USER
    # Weight-bearing columns -- exported with a "(kg)"/"(lbs)" header
    # suffix (ADR-0003) so the archive is self-describing per column
    # without re-deriving the account's unit each time.
    weight_cols: tuple[str, ...] = ()
    # Column subset + order for this member's CSV. None means "every
    # model field, in declaration order". GripType is deliberately
    # trimmed to (id, name): dimension_name is fixed seed data, not
    # something a restore needs to carry.
    fields: tuple[str, ...] | None = None

    @property
    def filename(self) -> str:
        return f"{self.model.__name__}.csv"

    @property
    def csv_fields(self) -> list[str]:
        if self.fields is not None:
            return list(self.fields)
        return list(self.model.model_fields.keys())


# Order here is the archive's canonical member order. TrainingSession is
# listed before the members that key off it (PainReport, WarmupStepCheck,
# SessionMaxEstimate, WorkSet) so a future importer that walks this list
# top-to-bottom can build its old->new TrainingSession id map before it
# needs it.
ARCHIVE_MEMBERS: tuple[ArchiveMember, ...] = (
    ArchiveMember(GripType, scope=Scope.GLOBAL, fields=("id", "name")),
    ArchiveMember(PlateInventoryItem, scope=Scope.USER, weight_cols=("weight",)),
    ArchiveMember(BodyWeightLog, scope=Scope.USER, weight_cols=("weight",)),
    ArchiveMember(Climb, scope=Scope.USER),
    ArchiveMember(MaxWeightTest, scope=Scope.USER, weight_cols=("weight",)),
    ArchiveMember(TrainingSession, scope=Scope.USER),
    ArchiveMember(PainReport, scope=Scope.TRAINING_SESSION),
    ArchiveMember(WarmupStepCheck, scope=Scope.TRAINING_SESSION),
    ArchiveMember(SessionMaxEstimate, scope=Scope.TRAINING_SESSION, weight_cols=("weight",)),
    ArchiveMember(WorkSet, scope=Scope.TRAINING_SESSION, weight_cols=("weight",)),
)


def scoped_query(
    member: ArchiveMember, user: User, training_session_ids: list[int] | None = None
) -> SelectOfScalar[Any]:
    """The SELECT that scopes `member`'s rows to `user` for export.

    `training_session_ids` is required (may be empty) for
    Scope.TRAINING_SESSION members -- it's the caller's job to have already
    looked up the user's TrainingSession ids (they come from the USER-scoped
    TrainingSession member, not from this function).
    """
    model = member.model
    if member.scope is Scope.GLOBAL:
        return select(model)
    if member.scope is Scope.USER:
        return select(model).where(model.user_id == user.id)
    if member.scope is Scope.TRAINING_SESSION:
        ids = training_session_ids if training_session_ids is not None else []
        return select(model).where(model.training_session_id.in_(ids))
    raise AssertionError(f"unhandled scope: {member.scope}")
