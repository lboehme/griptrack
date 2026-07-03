# Model a real per-user plate inventory instead of generic plate rounding

Ramp/warmup suggestions need to round computed %-of-max weights to something
actually loadable mid-session. The original plan deferred real plate
tracking to a post-MVP stretch goal, defaulting to rounding against a generic
"normal plate layout" assumption. We decided to build real plate-inventory
tracking into the core build instead: a per-user `PlateInventory` (plate
weight_kg + count owned), modeled as a single stack (block-pull loading is
one pin/handle, not split two-sided like a barbell), rounding suggestions
*down* to the nearest achievable total so a suggestion is never physically
unloadable. New users get a seeded default inventory they can edit.

Rejected alternative: a fixed rounding increment (e.g. nearest 1.25kg)
regardless of what plates someone owns — simpler, but the suggested number
may not be loadable as-is, which undermines the "usable in seconds between
sets" goal.
