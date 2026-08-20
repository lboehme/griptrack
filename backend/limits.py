"""Upper bounds on form/query inputs.

Generous enough that no real finger-training value ever hits them, tight
enough to keep absurd inputs from becoming a DoS — notably the plate
subset-sum in plates.round_down_to_loadable, whose cost scales with plate
count and target weight.
"""

MAX_WEIGHT = 1000        # kg or lbs; covers any bodyweight or block-pull load
MAX_NAME_LENGTH = 60     # display name (user text, not numeric)
MAX_GRADE_LENGTH = 32    # climb grade string ("V5", "7A+", odd local scales)
MAX_NOTES_LENGTH = 2000  # free-text climb notes
MAX_REPS = 1000
MAX_SET_NUMBER = 100
MAX_EDGE_MM = 1000
MAX_PLATE_WEIGHT = 1000
MAX_PLATE_COUNT = 100
MAX_SESSION_NUMBER = 20

# Training protocol settings (rep target and rest duration, #127)
MIN_REP_TARGET = 1
MAX_REP_TARGET = 30
MIN_BASE_WORK_SET_REPS = MIN_REP_TARGET
MAX_BASE_WORK_SET_REPS = MAX_REP_TARGET

MIN_REST_SECONDS = 15
MAX_REST_SECONDS = 1800
MIN_DEFAULT_REST_SECONDS = MIN_REST_SECONDS
MAX_DEFAULT_REST_SECONDS = MAX_REST_SECONDS


# Import (backend.archive, #102, #120) is an untrusted-file ingress point:
# a personal instrument's own export archive is tiny, so these bounds are
# generous headroom, not a real-usage estimate — they exist to cap the work
# a malicious or corrupted upload can force (zip-bomb guard, ADR-0008).
MAX_IMPORT_UPLOAD_BYTES = 20 * 1024 * 1024   # 20 MB compressed archive
MAX_IMPORT_MEMBER_BYTES = 50 * 1024 * 1024   # per-CSV decompressed cap
MAX_IMPORT_MEMBERS = 32                      # manifest + the fixed archive member set, with headroom
MAX_IMPORT_ROWS_PER_MEMBER = 50_000
