"""Upper bounds on numeric form/query inputs.

Generous enough that no real finger-training value ever hits them, tight
enough to keep absurd inputs from becoming a DoS — notably the plate
subset-sum in plates.round_down_to_loadable, whose cost scales with plate
count and target weight.
"""

MAX_WEIGHT = 1000        # kg or lbs; covers any bodyweight or block-pull load
MAX_REPS = 1000
MAX_SET_NUMBER = 100
MAX_EDGE_MM = 1000
MAX_PLATE_WEIGHT = 1000
MAX_PLATE_COUNT = 100
