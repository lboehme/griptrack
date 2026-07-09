# GripTrack is a personal instrument, not a public product

Decided 2026-07-09, during the planning session over
`docs/griptrack-full-review.md`. That review's strongest strategic point
(§1) was that several open threads — open signup, benchmarking, coach
views, learned-model AI, the whole public-launch apparatus — are only
rational under one of three futures: personal instrument, public product,
or coach-mediated tool. Leaving the choice implicit invites scope creep
toward all three at once.

**Decision: GripTrack is a personal instrument** — the owner plus invited
friends — for the foreseeable future, with **open-sourcing (community
self-hosting) as the candidate growth path** in a few months, rather than
a hosted public launch.

Consequences:

- The public-launch track is dropped from planning entirely: no email
  infrastructure, no open signup, no 2FA, no privacy-policy/GDPR
  apparatus, no monetization design. Invite-only registration (ADR 0004)
  stays the permanent model, not an MVP stopgap.
- Deferred security/UX work gets **named triggers instead of dates**:
  CSP nonces, an admin audit table, and first-run onboarding are triggered
  by open-sourcing or audience growth, not scheduled.
- Open-source intent mildly raises the standing value of documentation
  quality, secrets hygiene, and data export (a self-hoster's exit ramp is
  the same feature as a user's exit ramp) — CSV export is in scope now
  partly for this reason.
- Features are evaluated against "does this serve the owner and friends?"
  — which is why Tindeq/force-gauge integration and sport-climb analytics
  were cut, while training-signal correctness (deload-aware plateau,
  Spearman correlation, RPE-driven suggestions) ranks high: at this scale
  the analytics' only audience is the people training by them.

Revisit if the invited-friends group outgrows manual admin (dozens of
users), or if open-sourcing generates real self-hosting demand.
