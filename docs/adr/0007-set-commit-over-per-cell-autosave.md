# Commit a work set as a whole, not cell by cell

The original work-sets screen was a table with one editable cell per
(hand, set): weight, reps and RPE were number inputs, and every change
autosaved on its own. A `WorkSet` row came into existence when the user
ticked that cell's "done" checkbox. This followed the general rule stated
in CLAUDE.md — every interaction autosaves immediately, there is no final
"submit" step.

The "Focus" redesign replaces that table with one set at a time: two hand
cards (Left above Right), each with tap-to-adjust steppers, and a single
"Set done" button underneath. The button is what writes the set, so the
unit of persistence becomes **the set**, not the field — a single atomic
`POST /session/set` writing both hands' `WorkSet` rows in one transaction.

We chose the atomic commit over firing the existing per-hand
`POST /session/workset` twice. Two requests can half-fail on gym wifi,
leaving the left hand logged and the right hand not while the UI has
already advanced to the next set, and detecting that requires client-side
reconciliation we would rather not own. `/session/workset` remains as the
per-hand primitive — it is the seam most tests seed data through, and it
is the no-JS fallback target.

This is a smaller departure from "autosave immediately" than it first
looks. Ticking a cell was already an explicit commit gesture; the
prefilled weight and reps were never persisted before it. What actually
changes is the granularity — one gesture now commits both hands of one
set instead of one hand's one field — and the fact that the stepper's
in-progress value is unsaved client state until the button is pressed.
Everything else on the screen (session notes, the deload flag, pain
reports) keeps autosaving per interaction, and a `TrainingSession` can
still exist in a partially-filled state.

The cost is that a set is no longer freely editable in place. Corrections
go through an explicit edit mode: tapping a completed row reloads that
set into the cards, and the same commit path saves it. We accepted one
editing surface with a mode over two editing surfaces kept in sync.
