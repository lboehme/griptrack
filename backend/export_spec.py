"""Backward-compatibility shim for backend.archive (Ticket #120)."""

from backend.archive import (
    ARCHIVE_MEMBERS,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    ArchiveMember,
    Scope,
    neutralize,
    reverse_neutralize,
    scoped_query,
)

__all__ = [
    "ARCHIVE_MEMBERS",
    "FORMAT_VERSION",
    "MANIFEST_FILENAME",
    "ArchiveMember",
    "Scope",
    "neutralize",
    "reverse_neutralize",
    "scoped_query",
]
