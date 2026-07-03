# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — single-context repo, no `CONTEXT-MAP.md`.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

## File structure

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-bodyweight-and-max-weight-as-time-series.md
│   ├── 0002-real-plate-inventory-for-rounding.md
│   ├── 0003-native-unit-storage.md
│   ├── 0004-invite-only-registration.md
│   └── 0005-training-protocol-as-config-not-constants.md
└── backend/   ← not yet created (Phase 0)
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding — e.g. "Contradicts ADR-0003 (native-unit storage) — but worth reopening because…"
