"""Backward-compatibility shim for backend.archive (Ticket #120)."""

from backend.archive import (
    DATA_BEARING_MODELS,
    MAX_IMPORT_MEMBER_BYTES,
    MAX_IMPORT_MEMBERS,
    MAX_IMPORT_ROWS_PER_MEMBER,
    MAX_IMPORT_UPLOAD_BYTES,
    ArchiveError,
    ArchiveMember,
    ArchiveRestoreError,
    ImportRestoreError,
    Scope,
    account_has_data,
    restore_archive,
)

__all__ = [
    "DATA_BEARING_MODELS",
    "MAX_IMPORT_MEMBER_BYTES",
    "MAX_IMPORT_MEMBERS",
    "MAX_IMPORT_ROWS_PER_MEMBER",
    "MAX_IMPORT_UPLOAD_BYTES",
    "ArchiveError",
    "ArchiveMember",
    "ArchiveRestoreError",
    "ImportRestoreError",
    "Scope",
    "account_has_data",
    "restore_archive",
]
