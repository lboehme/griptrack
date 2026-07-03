# Store weights in the user's native unit, not canonical kg

Real plates are physically fixed in either kg increments (1.25/2.5/5/10/15/
20/25) or lb increments (2.5/5/10/25/35/45) — these don't convert cleanly
into each other. Storing all weight values canonically in kg, as originally
planned, would turn an lb-plate `PlateInventory` into ugly non-round kg
numbers and break the plate-rounding math against a user's real equipment.

Decision: weight values (`BodyWeightLog`, `MaxWeightTest`, `WorkSet.weight`,
`PlateInventory`) are stored in the user's `UnitPreference` natively, with no
canonical-unit conversion at storage time. `UnitPreference` is chosen at
signup and switching it later isn't supported (would require re-entering
plate inventory and accepting rounding artifacts on historical data).

This doesn't compromise the %bodyweight-vs-climb-grade analysis: it's a
ratio (weight ÷ bodyweight) within one user's consistently-chosen unit, so
it's unit-agnostic. A cross-user comparison needing a common unit would
convert at query time, not storage time — no such feature exists yet.
