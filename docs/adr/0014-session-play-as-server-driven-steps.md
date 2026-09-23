# A training session is one page whose steps the server renders

Decided 2026-09-23, in the redesign grill that followed the UI review
(`docs/ui-review-2026-09.md`, Direction D2). Refines how the Focus screens are
built (issues #76–#83). ADR-0007 (atomic set commit) is unchanged.

Today a session is two server-rendered pages, the warmup card ladder and the
Focus work-set screen, plus about 970 lines of vanilla JS on the work-set page.
The redesign treats a session as **one screen that moves forward**: warmup rung
→ rung → work set → rest → set → … → summary, with no tab bar and no page
reloads, and it must resume at the right place after a pause, a dark-mode switch
or Android killing the app.

## Decision

**`/session/play` is a single page. Each step (warmup rung, work set, rest,
summary) is a server-rendered fragment. Each action posts to the server, which
answers with the next step's fragment, and htmx swaps it in. The server derives
the current step from persisted state.**

- **Where am I?** The server works it out from what is saved: warmup steps
  recorded, work sets committed for the session's planned set count, whether
  `finished_at` is set. The page therefore always lands on the right step,
  which makes resume free, with no client-side state to restore.
- **Persistence is unchanged.** A set is still one atomic `POST` writing both
  hands (ADR-0007). Warmup ticks, notes, deload and pain reports still autosave
  per interaction.
- **Progressive enhancement stays.** Without htmx, the same endpoints answer
  with a redirect to `/session/play`, which renders the current step as a full
  page.
- **JS is limited to** the steppers (loadable-ladder walking, hold-to-repeat),
  the rest countdown (computed from a stored end time, never a decrementing
  counter), and calls to the native rest bridge (ADR-0015), which are
  feature-detected.
- **Rest is a step, not an overlay.** After a non-final set commit the server
  returns the rest step. Skipping, or the countdown reaching zero, requests the
  next set step.
- **The summary is the last step.** It asks for **session RPE** (1–10, as five
  chips: 3/5/7/9/10) and holds notes, the deload flag and tweaks. **Finish**
  stamps `TrainingSession.finished_at`. Session RPE and `finished_at` are new
  nullable columns on `training_sessions`, and **session load** (session RPE ×
  duration in minutes) is derived, not stored.
- The old `/session/warmup` and `/session/worksets` redirect to
  `/session/play` once it ships.

## Alternatives rejected

- **Keep two pages and restyle them.** Least work, but it keeps a reload
  between phases and a separate resume problem.
- **A client-side player driven by a JSON plan.** Smoothest, but it moves the
  step logic into JS, where the HTTP-seam tests can't see it (only Playwright
  can). It also contradicts the project's "htmx first, vanilla JS only where
  htmx can't reach" rule.

## Consequences

- Most of the existing Focus JS gets split up or rewritten. The step fragments
  are tested at the HTTP seam: each action's response names the next step. A
  small Playwright layer keeps covering the steppers and the countdown.
- Session RPE plus duration gives the overtraining warning and the deferred
  injury guardian (#28) a standard load signal.
- Deferred to a later pass: the new-best badge and the volume bars on the
  summary.
