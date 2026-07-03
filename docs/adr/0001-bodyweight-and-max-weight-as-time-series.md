# Track bodyweight and max weight as time series, not point-in-time fields

The original (learning-project) plan stored `bodyweight_kg` and per-hand max
weight as single mutable fields on the user profile. Once the project's scope
stopped being constrained by "keep it simple enough to learn from," we
switched both to append-only history (`BodyWeightLog`, `MaxWeightTest`)
instead, so the %bodyweight-vs-climb-grade correlation analysis can use the
bodyweight/max-weight that was actually true at the time of each
TrainingSession, rather than applying today's value retroactively across a
user's whole history. A side effect: the previously-deferred "testing session
to establish max weight" feature is no longer a stretch goal — it's simply
how rows get added to `MaxWeightTest`, so it's part of the core build now.
