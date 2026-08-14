"""Restore an Export archive into an empty account (ADR-0008, #102).

Reads the same `backend.export_spec.ARCHIVE_MEMBERS` list the exporter
(`backend.routers.profile.export_data`) writes from, so the two directions
of the round trip can't drift apart: each member's `Scope` tells this module
how to re-attach its rows to the importing user exactly the way it told the
exporter how to filter them.

Untrusted-file ingress (ADR-0008): bounded upload size, per-member
decompressed size, member count, and row count (zip-bomb guard, all via
`backend.limits`); reverses the exporter's S6 formula-neutralization; the
whole load is one transaction, so any failure rolls the account back to
empty.
"""

import csv
import io
import json
import types
import typing
import zipfile
from datetime import date as date_type
from datetime import datetime

from sqlmodel import Session, SQLModel, select

from backend.export_spec import (
    ARCHIVE_MEMBERS,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    ArchiveMember,
    Scope,
    reverse_neutralize,
)
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
    PlateInventoryItem,
    TrainingSession,
    User,
)

# The models an empty account is defined against (ADR-0008): any row here
# for the user means the account already "has data". Seeded default
# PlateInventoryItem rows deliberately don't count.
DATA_BEARING_MODELS = (TrainingSession, Climb, MaxWeightTest, BodyWeightLog)


class ImportRestoreError(Exception):
    """A rejected import. The message is user-facing (names the offending
    file/row where possible) -- routers can render it directly."""


def account_has_data(session: Session, user: User) -> bool:
    for model in DATA_BEARING_MODELS:
        row = session.exec(
            select(model.id).where(model.user_id == user.id).limit(1)
        ).first()
        if row is not None:
            return True
    return False


def restore_archive(session: Session, user: User, upload_bytes: bytes) -> None:
    """Validate and load `upload_bytes` (a ZIP, as produced by
    `GET /profile/export`) into `user`'s account. Raises
    `ImportRestoreError` -- with nothing written, since every write happens
    inside the try/rollback below -- for every problem this module itself
    detects: a non-empty account, an unrecognized/incomplete archive, an
    unresolvable grip/session reference, or a bound violation. A DB-level
    failure this module doesn't anticipate (e.g. an unexpected constraint
    violation) still rolls back cleanly but propagates as-is, not as
    `ImportRestoreError`."""

    if len(upload_bytes) > MAX_IMPORT_UPLOAD_BYTES:
        raise ImportRestoreError("Archive is too large.")

    if account_has_data(session, user):
        raise ImportRestoreError(
            "This account already has data. Import only restores into an "
            "empty account -- see the CSV import docs for restoring into a "
            "fresh account."
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(upload_bytes))
    except zipfile.BadZipFile as exc:
        raise ImportRestoreError("Not a valid export archive (zip).") from exc

    if len(zf.infolist()) > MAX_IMPORT_MEMBERS:
        raise ImportRestoreError("Archive contains too many files.")

    names = set(zf.namelist())
    required = {MANIFEST_FILENAME} | {m.filename for m in ARCHIVE_MEMBERS}
    missing = required - names
    if missing:
        raise ImportRestoreError(
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
                        member, row_num, parsed, user,
                        training_session_id_map, grip_name_by_old_id, local_grip_id_by_name,
                    )
                    session.add(obj)
                    pending.append((int(parsed["id"]), obj))  # type: ignore[arg-type]
                session.flush()
                for old_id, obj in pending:
                    training_session_id_map[old_id] = obj.id  # type: ignore[assignment]
                continue

            for row_num, parsed in rows:
                obj = _build_row(
                    member, row_num, parsed, user,
                    training_session_id_map, grip_name_by_old_id, local_grip_id_by_name,
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
        raise ImportRestoreError("manifest.json is not valid JSON.") from exc

    if manifest.get("format_version") != FORMAT_VERSION:
        raise ImportRestoreError(
            "Unsupported or outdated export: unrecognized format_version."
        )
    if manifest.get("unit") not in VALID_UNITS:
        raise ImportRestoreError("manifest.json has an invalid unit.")
    return manifest


def _safe_read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    """Read `name` out of `zf`, capped at MAX_IMPORT_MEMBER_BYTES of
    *decompressed* output regardless of what the zip's central directory
    claims -- the zip-bomb guard (ADR-0008)."""
    try:
        with zf.open(name) as f:
            data = f.read(MAX_IMPORT_MEMBER_BYTES + 1)
    except KeyError as exc:
        raise ImportRestoreError(f"{name} is missing from the archive.") from exc
    if len(data) > MAX_IMPORT_MEMBER_BYTES:
        raise ImportRestoreError(f"{name} exceeds the maximum allowed size.")
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
        raise ImportRestoreError(f"{member.filename} is not valid UTF-8.") from exc

    renames = member.renames(unit)
    expected_header = member.header(unit)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != expected_header:
        raise ImportRestoreError(
            f"{member.filename}: unexpected columns -- archive doesn't match "
            "this format version."
        )
    inverse_renames = {v: k for k, v in renames.items()}

    rows: list[tuple[int, dict[str, object]]] = []
    for row_num, csv_row in enumerate(reader, start=2):
        if row_num - 1 > MAX_IMPORT_ROWS_PER_MEMBER:
            raise ImportRestoreError(f"{member.filename}: too many rows.")
        parsed: dict[str, object] = {}
        for header, raw_value in csv_row.items():
            field = inverse_renames.get(header, header)
            value = reverse_neutralize(raw_value) if raw_value is not None else ""
            try:
                parsed[field] = _convert_cell(member.model, field, value)
            except (ValueError, TypeError) as exc:
                # A malformed cell (non-numeric text in an int/float column,
                # an unparseable date) must fail the import cleanly with a
                # 400 that points at the exact cell -- never escape as a 500.
                raise ImportRestoreError(
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
            raise ImportRestoreError(
                f"{member.filename} row {row_num}: references an unknown "
                f"training session (id {old_ts_id})"
            )
        kwargs["training_session_id"] = new_ts_id

    if "grip_type_id" in kwargs:
        old_grip_id = kwargs["grip_type_id"]
        name = grip_name_by_old_id.get(old_grip_id)
        local_id = local_grip_id_by_name.get(name) if name is not None else None
        if local_id is None:
            raise ImportRestoreError(
                f"{member.filename} row {row_num}: unknown grip type "
                f"(id {old_grip_id} in the archive)"
            )
        kwargs["grip_type_id"] = local_id

    return member.model(**kwargs)
