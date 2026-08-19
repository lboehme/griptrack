"""Unified lifecycle for Export archive and Account restore (ADR-0008, CONTEXT.md).

Single source of truth for the archive format specification, format versioning,
S6 spreadsheet-formula neutralization, archive generation (`create_archive`),
and account restoration into empty accounts (`restore_archive`).

The archive is a versioned ZIP containing `manifest.json` plus one CSV per model
defined in `ARCHIVE_MEMBERS`. Grips are resolved by name, weights are stored in
the account's native UnitPreference (ADR-0003), and primary keys are discarded
during restore to guarantee isolation.
"""

import csv
import io
import json
import types
import typing
import zipfile
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlmodel import Session, SQLModel, select
from sqlmodel.sql.expression import SelectOfScalar

from backend.limits import (
    MAX_IMPORT_MEMBER_BYTES,
    MAX_IMPORT_MEMBERS,
    MAX_IMPORT_ROWS_PER_MEMBER,
    MAX_IMPORT_UPLOAD_BYTES,
)
from backend.models import (
    VALID_UNITS,
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

# Re-export limits so tests / callers can inspect or patch them on backend.archive
MAX_IMPORT_UPLOAD_BYTES = MAX_IMPORT_UPLOAD_BYTES
MAX_IMPORT_MEMBER_BYTES = MAX_IMPORT_MEMBER_BYTES
MAX_IMPORT_MEMBERS = MAX_IMPORT_MEMBERS
MAX_IMPORT_ROWS_PER_MEMBER = MAX_IMPORT_ROWS_PER_MEMBER


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

    def renames(self, unit: str) -> dict[str, str]:
        """Weight column -> its `(kg)`/`(lbs)`-suffixed CSV header (ADR-0003).

        The one place the header-suffix convention is spelled out; both the
        exporter and the importer go through here (and `header`) so the two
        directions of the round trip can't drift apart.
        """
        return {col: f"{col} ({unit})" for col in self.weight_cols}

    def header(self, unit: str) -> list[str]:
        """This member's CSV header row: `csv_fields` with weight columns
        suffixed by `unit`."""
        renames = self.renames(unit)
        return [renames.get(f, f) for f in self.csv_fields]


def neutralize(value: Any) -> Any:
    """S6 CSV formula-neutralization: a text cell starting with `= + - @`
    would execute as a formula when the archive is opened in a spreadsheet,
    so prefix it with a single quote. `reverse_neutralize` is the exact
    inverse -- the two are a pair; change one and you must change the other.
    """
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def reverse_neutralize(value: str) -> str:
    """Inverse of `neutralize`: strip exactly one leading `'` guarding a
    `= + - @` cell.

    Known limitation: a genuine value that already reads `'=x` was exported
    verbatim (it doesn't start with `= + - @`, so the exporter never quoted
    it) but decodes back to `=x` here -- an inherent asymmetry of
    single-quote neutralization, not round-trip-safe for that rare case.
    """
    if len(value) >= 2 and value[0] == "'" and value[1] in "=+-@":
        return value[1:]
    return value


# Canonical member order: TrainingSession must precede members that key off it
# (PainReport, WarmupStepCheck, SessionMaxEstimate, WorkSet) so that an importer
# walking top-to-bottom can build its old->new id map before children need it.
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

# The models an empty account is defined against (ADR-0008): any row here
# for the user means the account already "has data". Seeded default
# PlateInventoryItem rows deliberately don't count.
DATA_BEARING_MODELS = (TrainingSession, Climb, MaxWeightTest, BodyWeightLog)


class ArchiveError(Exception):
    """A rejected archive operation (e.g. invalid format, bound violation,
    or non-empty restore attempt). The message is user-facing (names the
    offending file/row where possible) -- routers can render it directly."""


# Backward compatibility aliases
ImportRestoreError = ArchiveError
ArchiveRestoreError = ArchiveError


def scoped_query(
    member: ArchiveMember, user: User, training_session_ids: list[int] | None = None
) -> SelectOfScalar[Any]:
    """The SELECT that scopes `member`'s rows to `user` for export.

    `training_session_ids` is required (may be empty) for
    Scope.TRAINING_SESSION members -- it's the caller's job to have already
    looked up the user's TrainingSession ids.
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


def account_has_data(session: Session, user: User) -> bool:
    """True if `user` has any data in `DATA_BEARING_MODELS`."""
    for model in DATA_BEARING_MODELS:
        row = session.exec(
            select(model.id).where(model.user_id == user.id).limit(1)
        ).first()
        if row is not None:
            return True
    return False


def create_archive(session: Session, user: User) -> bytes:
    """Generate a versioned Export archive (ZIP bytes) for `user` (ADR-0008).

    Contains `manifest.json` plus one CSV per `ARCHIVE_MEMBERS` entry,
    with weight columns suffixed by `(kg)` or `(lbs)` per native-unit storage
    (ADR-0003), and cells formula-neutralized (S6).
    """

    def add_csv(zf: zipfile.ZipFile, filename: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: neutralize(v) for k, v in row.items()})
        zf.writestr(filename, csv_buffer.getvalue())

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "format_version": FORMAT_VERSION,
            "unit": user.unit_pref,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, indent=2))

        # TRAINING_SESSION-scoped members (PainReport, WarmupStepCheck,
        # SessionMaxEstimate, WorkSet) need the user's TrainingSession ids
        # to scope their query. ARCHIVE_MEMBERS lists TrainingSession
        # before all of them, so one forward pass captures those ids
        # the moment TrainingSession is reached.
        training_session_ids: list[int] = []
        for member in ARCHIVE_MEMBERS:
            query = scoped_query(member, user, training_session_ids)
            rows = session.exec(query).all()
            if member.model is TrainingSession:
                training_session_ids = [r.id for r in rows if r.id is not None]
            renames = member.renames(user.unit_pref)
            out_fields = member.header(user.unit_pref)
            out_rows = [
                {renames.get(f, f): d[f] for f in member.csv_fields}
                for d in (r.model_dump() for r in rows)
            ]
            add_csv(zf, member.filename, out_rows, out_fields)

    return zip_buffer.getvalue()


def restore_archive(session: Session, user: User, upload_bytes: bytes) -> None:
    """Validate and load `upload_bytes` (a ZIP, as produced by `create_archive`)
    into `user`'s account (ADR-0008).

    Raises `ArchiveError` if the account already has data, if the archive is
    unrecognized/incomplete/corrupt, if grip/session references cannot be resolved,
    or if any safety bound is exceeded.

    All inserts happen in an atomic transaction; on failure, the account rolls
    back to empty.
    """
    if len(upload_bytes) > MAX_IMPORT_UPLOAD_BYTES:
        raise ArchiveError("Archive is too large.")

    if account_has_data(session, user):
        raise ArchiveError(
            "This account already has data. Import only restores into an "
            "empty account -- see the CSV import docs for restoring into a "
            "fresh account."
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(upload_bytes))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("Not a valid export archive (zip).") from exc

    if len(zf.infolist()) > MAX_IMPORT_MEMBERS:
        raise ArchiveError("Archive contains too many files.")

    names = set(zf.namelist())
    required = {MANIFEST_FILENAME} | {m.filename for m in ARCHIVE_MEMBERS}
    missing = required - names
    if missing:
        raise ArchiveError(
            "Unsupported or outdated export: missing " + ", ".join(sorted(missing))
        )

    manifest = _read_manifest(zf)
    unit = manifest["unit"]

    grip_member = next(m for m in ARCHIVE_MEMBERS if m.model is GripType)
    grip_name_by_old_id: dict[int, str] = {
        int(row["id"]): str(row["name"])
        for _, row in _read_member_rows(zf, grip_member, unit)
    }
    local_grip_id_by_name: dict[str, int] = {
        g.name: g.id for g in session.exec(select(GripType)).all() if g.id is not None
    }

    try:
        training_session_id_map: dict[int, int] = {}
        for member in ARCHIVE_MEMBERS:
            if member.model is GripType:
                continue  # global lookup data -- already seeded locally, never inserted

            if member.model is PlateInventoryItem:
                # Restoring plates replaces the seeded default inventory
                # (ADR-0008) -- a fresh account still carries those rows
                # even though they don't count toward "has data".
                for item in session.exec(
                    select(PlateInventoryItem).where(PlateInventoryItem.user_id == user.id)
                ):
                    session.delete(item)

            rows = _read_member_rows(zf, member, unit)

            if member.model is TrainingSession:
                pending: list[tuple[int, TrainingSession]] = []
                for row_num, parsed in rows:
                    obj = _build_row(
                        member,
                        row_num,
                        parsed,
                        user,
                        training_session_id_map,
                        grip_name_by_old_id,
                        local_grip_id_by_name,
                    )
                    session.add(obj)
                    pending.append((int(parsed["id"]), obj))  # type: ignore[arg-type]
                session.flush()
                for old_id, obj in pending:
                    training_session_id_map[old_id] = obj.id  # type: ignore[assignment]
                continue

            for row_num, parsed in rows:
                obj = _build_row(
                    member,
                    row_num,
                    parsed,
                    user,
                    training_session_id_map,
                    grip_name_by_old_id,
                    local_grip_id_by_name,
                )
                session.add(obj)

        # ADR-0008 frames this as "adopt the manifest's unit, refusing only
        # on a conflicting existing unit" -- but registration always gives
        # a user *some* unit_pref, and the empty-account gate above already
        # guarantees no weight-bearing row exists under it yet, so there's
        # no data-level conflict left to refuse: the manifest's unit always
        # wins for an account that passed that gate.
        user.unit_pref = unit
        session.add(user)
        session.commit()
    except Exception:
        session.rollback()
        raise


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    raw = _safe_read_member(zf, MANIFEST_FILENAME)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError("manifest.json is not valid JSON.") from exc

    if not isinstance(manifest, dict):
        raise ArchiveError("manifest.json must be a JSON object.")

    if manifest.get("format_version") != FORMAT_VERSION:
        raise ArchiveError(
            "Unsupported or outdated export: unrecognized format_version."
        )
    if manifest.get("unit") not in VALID_UNITS:
        raise ArchiveError("manifest.json has an invalid unit.")
    return manifest


def _safe_read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    """Read `name` out of `zf`, capped at MAX_IMPORT_MEMBER_BYTES of
    *decompressed* output regardless of what the zip's central directory
    claims -- the zip-bomb guard (ADR-0008)."""
    try:
        with zf.open(name) as f:
            data = f.read(MAX_IMPORT_MEMBER_BYTES + 1)
    except KeyError as exc:
        raise ArchiveError(f"{name} is missing from the archive.") from exc
    if len(data) > MAX_IMPORT_MEMBER_BYTES:
        raise ArchiveError(f"{name} exceeds the maximum allowed size.")
    return data


def _field_type(model: type[SQLModel], field_name: str) -> tuple[type, bool]:
    """(base type, nullable) for `model`'s `field_name`, unwrapping `X |
    None` annotations."""
    annotation = model.model_fields[field_name].annotation
    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return (args[0] if args else str), True
    return annotation, False  # type: ignore[return-value]


def _convert_cell(model: type[SQLModel], field_name: str, raw: str) -> object:
    base, nullable = _field_type(model, field_name)
    if raw == "":
        return None if nullable else raw
    if base is int:
        return int(raw)
    if base is float:
        return float(raw)
    if base is bool:
        return raw == "True"
    if base is date_type:
        return date_type.fromisoformat(raw)
    if base is datetime:
        return datetime.fromisoformat(raw)
    return raw


def _read_member_rows(
    zf: zipfile.ZipFile, member: ArchiveMember, unit: str
) -> list[tuple[int, dict[str, object]]]:
    """Parse `member`'s CSV into `(row_number, {field: typed_value})`
    pairs, row_number starting at 2 (the header is row 1) so error messages
    line up with what a spreadsheet would show."""
    raw = _safe_read_member(zf, member.filename)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveError(f"{member.filename} is not valid UTF-8.") from exc

    renames = member.renames(unit)
    expected_header = member.header(unit)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != expected_header:
        raise ArchiveError(
            f"{member.filename}: unexpected columns -- archive doesn't match "
            "this format version."
        )
    inverse_renames = {v: k for k, v in renames.items()}

    rows: list[tuple[int, dict[str, object]]] = []
    for row_num, csv_row in enumerate(reader, start=2):
        if row_num - 1 > MAX_IMPORT_ROWS_PER_MEMBER:
            raise ArchiveError(f"{member.filename}: too many rows.")
        parsed: dict[str, object] = {}
        for header, raw_value in csv_row.items():
            if header is None:
                raise ArchiveError(
                    f"{member.filename} row {row_num}: row has more columns than the header."
                )
            field = inverse_renames.get(header, header)
            value = reverse_neutralize(raw_value) if raw_value is not None else ""
            try:
                parsed[field] = _convert_cell(member.model, field, value)
            except (ValueError, TypeError) as exc:
                # A malformed cell (non-numeric text in an int/float column,
                # an unparseable date) must fail the import cleanly with a
                # 400 that points at the exact cell -- never escape as a 500.
                raise ArchiveError(
                    f"{member.filename} row {row_num}, column {header!r}: "
                    f"invalid value {value!r}."
                ) from exc
        rows.append((row_num, parsed))
    return rows


def _build_row(
    member: ArchiveMember,
    row_num: int,
    parsed: dict[str, object],
    user: User,
    training_session_id_map: dict[int, int],
    grip_name_by_old_id: dict[int, str],
    local_grip_id_by_name: dict[str, int],
) -> SQLModel:
    """One archive row -> a fresh model instance attached to `user`. File
    PKs are always discarded; `user_id`/`training_session_id`/
    `grip_type_id` are rewired per ADR-0008 -- never trusted from the file."""
    kwargs = {k: v for k, v in parsed.items() if k != "id"}

    if member.scope is Scope.USER:
        kwargs["user_id"] = user.id
    elif member.scope is Scope.TRAINING_SESSION:
        old_ts_id = kwargs.pop("training_session_id")
        new_ts_id = training_session_id_map.get(old_ts_id)
        if new_ts_id is None:
            raise ArchiveError(
                f"{member.filename} row {row_num}: references an unknown "
                f"training session (id {old_ts_id})"
            )
        kwargs["training_session_id"] = new_ts_id

    if "grip_type_id" in kwargs:
        old_grip_id = kwargs["grip_type_id"]
        name = grip_name_by_old_id.get(old_grip_id)
        local_id = local_grip_id_by_name.get(name) if name is not None else None
        if local_id is None:
            raise ArchiveError(
                f"{member.filename} row {row_num}: unknown grip type "
                f"(id {old_grip_id} in the archive)"
            )
        kwargs["grip_type_id"] = local_id

    return member.model(**kwargs)
