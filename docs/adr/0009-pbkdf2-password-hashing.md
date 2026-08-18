# Password hashing is stdlib PBKDF2, not a native KDF wheel

GripTrack hashed passwords with `bcrypt` from the first auth work (ADR-0004).
`bcrypt` has been a Rust extension since 4.0, and the Android pivot (PRD #93)
runs the *unchanged* backend on-device via Chaquopy, where every native wheel
must be cross-compiled for `arm64-v8a` and proven to import. The #97 feasibility
work confirmed both of GripTrack's Rust deps — `bcrypt` and `pydantic-core` —
*can* be self-built with `cibuildwheel` and run under Chaquopy, but each such
wheel is standing maintenance: a per-release cross-compile the build must own,
because neither publishes Android wheels on PyPI. `pydantic-core` is the engine
under Pydantic v2 / SQLModel and can't be cheaply removed. `bcrypt` can.

## Decision

**Hash passwords with stdlib `hashlib.pbkdf2_hmac` (PBKDF2-HMAC-SHA256), and
drop the `bcrypt` dependency entirely.** `backend.auth` already hid hashing
behind `hash_password` / `verify_password`, so no caller changed.

- **Self-describing stored format:** `pbkdf2_sha256$<iterations>$<b64salt>$<b64hash>`.
  The iteration count lives in each hash, so it can be raised later without
  invalidating existing hashes — `verify_password` reads the stored iterations.
- **Iterations: 600,000** (OWASP's 2023 floor for PBKDF2-HMAC-SHA256), 16-byte
  random salt per hash, verification via `hmac.compare_digest` (constant-time).
- **Fails closed:** any malformed or legacy (`$2b$…` bcrypt) stored hash makes
  `verify_password` return `False` rather than raise. The timing-equalized
  dummy-verify for unknown emails and the per-IP login rate limiter are
  unchanged.
- **Password length bound raised off bcrypt's 72 bytes** (`PASSWORD_MAX_BYTES`,
  now 1024). PBKDF2 hashes the whole input, so the old cap was a bcrypt
  artifact; the remaining bound is DoS hygiene, not correctness. The 8-char
  floor stays.

## Migration: reset-on-cutover

bcrypt hashes can't be verified once bcrypt is gone from the runtime. Rather
than carry a dual-verify transition (only possible where bcrypt is still
installed — i.e. the legacy Fly deploy, never on-device), existing accounts are
**reset on cutover**: the admin resets them, or they re-register. This fits the
on-device story, where a phone is seeded by a fresh install + CSV import (#100)
that creates accounts from scratch. The Export/import archive (ADR-0008)
**does not carry `hashed_password`**, so the format change doesn't affect
round-trips.

## Consequences / trade-offs

- **Weaker per-iteration than bcrypt/argon2 against GPU attackers.** PBKDF2 is a
  NIST-approved KDF and, at 600k iterations with a per-user salt behind login
  rate limiting, is a reasonable choice for a **personal, invite-only
  instrument** (ADR-0006). Flag this if the threat model ever changes (public
  signup, an audience) — that would be the trigger to reconsider argon2, and to
  weigh the native-wheel cost again.
- **`argon2` / `scrypt` were the stronger-KDF alternatives** but are native
  extensions — they reintroduce exactly the arm64 cross-compile burden this ADR
  removes, so they're out for the on-device target.
- **Keeping bcrypt (self-built wheel)** was viable after #97 proved the
  cibuildwheel path, but leaves two per-release wheels to maintain instead of
  one. Dropping bcrypt halves that surface; after this change `pydantic-core` is
  the *only* hard native wheel the Android build must supply.
