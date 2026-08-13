# Export/import is a versioned round-trip, restoring only into an empty account

GripTrack has shipped CSV **export** (`GET /profile/export`) since Wave 2 — a
ZIP of per-model CSVs. Issue #100 adds the other direction: **import**. The
motivating case is the Android build (#93), which makes the phone the sole data
home with no server, so the owner needs a supported way to seed a fresh
on-device database from their existing Fly data. This ADR records the shape of
that round trip and, deliberately, what it refuses to do.

## Decision

**Import restores an Export archive into an empty account only.** It refuses if
the target account already holds data — defined as any `TrainingSession`,
`Climb`, `MaxWeightTest`, or `BodyWeightLog` row for that user (seeded default
plates don't count). There is no merge, upsert, or append.

**The archive is a versioned contract, not a loose pile of CSVs.** The export
gains a `manifest.json` (`format_version`, `unit`, `exported_at`), and import
validates it: an archive without a recognized `format_version`, or missing a
required member, is rejected as unsupported/outdated. The archive is the source
of truth for the account's unit — read from the manifest, not sniffed from the
`weight (<unit>)` column-header suffixes.

**Grips resolve by name, not by id.** The export today stores a raw
`grip_type_id` but carries no `GripType` table, so ids only line up if seeding
is byte-for-byte deterministic across databases. The format grows a
`GripType.csv` (id + `name`); import resolves each referenced grip **by name**
to the local id and fails loud on an unknown grip. The export also grows
`PlateInventoryItem.csv` so a user's real plate inventory round-trips; a restore
without it would silently drop to seeded defaults. `TrainingProtocol` (no
per-user rows exist yet) and `User` settings (`name`, `hand_order_pref`, which
come from registration) stay out of the archive.

**All file-supplied primary keys are discarded.** Every imported row is inserted
fresh and attached to the **current logged-in user** — `user_id` comes from the
session, never from the file. Parent `TrainingSession`s get an old→new id map
that rewires their children (`WorkSet`, `PainReport`, `WarmupStepCheck`,
`SessionMaxEstimate`); `grip_type_id` is rewired via the name map. The whole
import is a single all-or-nothing transaction: any validation failure rolls
everything back and names the offending file+row, leaving the account empty.

**Units are adopted, never converted.** Because the target is a brand-new
account, import sets its `unit_pref` from the manifest. It refuses only if the
account somehow already carries a conflicting unit. kg↔lbs conversion is
explicitly not done — see below.

## Why

- **Restore-into-empty dodges the merge swamp.** A general merge needs a natural
  key for every table (what makes two `WorkSet`s "the same"?), idempotent
  re-import, and FK-collision handling — a large, error-prone surface for a
  personal instrument whose actual need is "seed my new phone from my export."
  Refusing on a non-empty account keeps rollback trivial and the code honest.
- **Attaching every row to the session's user is the isolation guarantee.**
  Trusting a file-supplied `user_id` would let one user's archive write rows
  under another user's id. Ignoring file PKs entirely makes cross-user leakage
  structurally impossible, and the security test writes itself.
- **By-name grip resolution and the manifest make the format survivable.** Ids
  are an implementation detail; names and an explicit `format_version` are the
  stable contract, so a future seed-list change or format revision doesn't
  silently corrupt a restore.
- **No unit conversion, per ADR-0003.** Weights are stored in the user's native
  unit precisely because real plates are physically kg- or lb-denominated;
  converting on import would reintroduce the unloadable non-round numbers that
  ADR-0003 exists to avoid. This ADR extends that decision to the round trip.

## Consequences

- The export format changes (adds `manifest.json`, `GripType.csv`,
  `PlateInventoryItem.csv`), so this is a real contract with a version number;
  pre-manifest archives are not importable. Acceptable because the archives that
  will be restored are produced by the new exporter.
- Import is an untrusted-file ingress point: it reuses `backend/limits.py`
  numeric bounds and adds upload-size, per-member decompressed-size, member-count
  and row-count caps (zip-bomb guard), plus a `tests/test_security.py` case.
- Export neutralizes spreadsheet-formula cells by prefixing a `'` (S6). Import
  must **reverse** that — strip a single leading `'` from cells starting
  `'= '+ '- '@` — or a round trip stores the quote verbatim.
- A genuine merge/append into a populated account remains possible as a later,
  separately-designed feature; nothing here forecloses it, but it is out of
  scope and unbuilt.
