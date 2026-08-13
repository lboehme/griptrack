"""On-device feasibility probe for GitHub issue #97 (GripTrack Android pivot,
PRD #93).

Proves two things under Chaquopy, on Python 3.12, on an arm64-v8a device:

  1. ``bcrypt`` (the Rust ``_bcrypt`` extension) imports and round-trips a
     real hash/verify cycle — the exact operation ``backend.auth`` performs
     on every login.
  2. ``pydantic_core`` (Rust) imports and can build + run a validator — the
     exact operation every SQLModel/Pydantic model relies on for every
     request.

Deliberately standalone and minimal: this does NOT import ``backend`` or any
project code. #97's scope is proving these two Rust wheels install and run
under Chaquopy at all, not embedding the real app (that's #98). See
docs/android-feasibility.md for the go/no-go criteria these checks feed.

Called from MainActivity via the Chaquopy Java/Python bridge:
    Python.getInstance().getModule("feasibility_check").callAttr("check_bcrypt")
"""

from __future__ import annotations


def check_bcrypt() -> str:
    """Import bcrypt and perform a real hashpw/checkpw round-trip.

    Raises on any failure (import error, ABI mismatch, wrong result) so the
    caller can surface a FAIL with the underlying exception message.
    """
    import bcrypt

    password = b"griptrack-97-feasibility-check"
    hashed = bcrypt.hashpw(password, bcrypt.gensalt())
    if not bcrypt.checkpw(password, hashed):
        raise AssertionError(
            "bcrypt.checkpw() returned False for the password it just hashed"
        )
    version = getattr(bcrypt, "__version__", "unknown")
    return f"bcrypt {version}: hashpw/checkpw round-trip OK"


def check_pydantic_core() -> str:
    """Import pydantic_core and run a real SchemaValidator round-trip.

    Mirrors what every Pydantic/SQLModel model does under the hood on every
    request: build a schema, then validate a value against it.
    """
    import pydantic_core
    from pydantic_core import SchemaValidator, core_schema

    validator = SchemaValidator(core_schema.int_schema())
    result = validator.validate_python("42")
    if result != 42:
        raise AssertionError(f"expected validate_python('42') == 42, got {result!r}")
    version = getattr(pydantic_core, "__version__", "unknown")
    return f"pydantic_core {version}: SchemaValidator round-trip OK"
