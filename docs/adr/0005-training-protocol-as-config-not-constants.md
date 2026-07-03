# Model the ramp/work-set protocol as a config row, not hardcoded constants

The ramp percentages (50/65/80/90% of CurrentMax) and base work-set rep
count (5) are fixed and identical for every user today. The obvious
implementation would be hardcoded constants in code. Instead, we model them
as a `TrainingProtocol` — a config table with a single global default row —
because the user wants the option to make these per-user-editable later.
Starting with a config concept (even with only one row in use) means adding
per-user overrides later is an additive schema change (a nullable user_id
override), not a rework of code that assumed fixed constants throughout.
