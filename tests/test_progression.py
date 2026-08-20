"""HTTP-seam tests for progression engine (issue #129, ADR-0011, ADR-0012)."""

import re

from backend.models import VALID_PROGRESSION_PATHS, ProgressionSettings
from tests.helpers import (
    get_session_page,
    grip_type_id,
    log_max_test,
    register,
    save_work_set,
)


def worksets_page(client, grip="half crimp", edge_mm=20, date="2026-07-04", hand=None, session_number=None):
    params = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
    }
    if hand is not None:
        params["hand"] = hand
    if session_number is not None:
        params["session_number"] = session_number
    return get_session_page(client, "/session/worksets", params)


def current_set_weight_input(page_text: str, hand: str) -> str | None:
    match = re.search(
        rf'\<input[^\>]*name="{hand}_weight"[^\>]*value="([^"]*)"', page_text
    )
    return match.group(1) if match else None


def autoreg_hint_text(page_text: str, hand: str) -> str | None:
    match = re.search(
        rf'data-role="autoreg-hint"[^>]*data-hand="{hand}"[^>]*>([^<]+)<', page_text
    )
    return match.group(1).strip() if match else None


def test_progression_settings_model_columns():
    """ProgressionSettings model defines expected schema and defaults."""
    setting = ProgressionSettings(
        user_id=1,
        path="weight",
        rep_min=5,
        rep_max=5,
        max_sets=6,
    )
    assert setting.user_id == 1
    assert setting.grip_type_id is None
    assert setting.edge_mm is None
    assert setting.path == "weight"
    assert setting.rep_min == 5
    assert setting.rep_max == 5
    assert setting.max_sets == 6
    assert "weight" in VALID_PROGRESSION_PATHS
    assert "set" in VALID_PROGRESSION_PATHS
    assert "double" in VALID_PROGRESSION_PATHS


def test_rpe_trigger_ready_when_two_sessions_hit_target_at_rpe_le_7(client):
    """When last 2 non-deload sessions hit target reps at RPE <= 7.0,
    an inline suggestion to add one loadable increment appears, and the stepper
    remains untouched."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "40.0")

    # Session 1 on 2026-07-01: 3 sets @ 40kg x 5 @ RPE 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")
        save_work_set(client, "right", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    # Session 2 on 2026-07-03: 3 sets @ 40kg x 5 @ RPE 6.5
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="6.5", date="2026-07-03")
        save_work_set(client, "right", s, "40.0", "5", rpe="6.5", date="2026-07-03")

    # Session 3 on 2026-07-05: check worksets page
    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200

    # Inline hint appears for both hands
    left_hint = autoreg_hint_text(page.text, "left")
    right_hint = autoreg_hint_text(page.text, "right")
    assert left_hint is not None
    assert "40.5" in left_hint
    assert right_hint is not None
    assert "40.5" in right_hint

    # Stepper values remain untouched at 40.0 (never pre-filled with suggestion)
    assert current_set_weight_input(page.text, "left") == "40.0"
    assert current_set_weight_input(page.text, "right") == "40.0"


def test_rpe_trigger_hold_when_rpe_ge_9(client):
    """When any working set in last 2 sessions has RPE >= 9.0, suggestion is withheld (silent)."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    # Session 1: all RPE 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    # Session 2: set 3 has RPE 9.0
    save_work_set(client, "left", 1, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 2, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 3, "40.0", "5", rpe="9.0", date="2026-07-03")

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is None


def test_rpe_trigger_hold_when_below_target_reps(client):
    """When any working set misses the rep target, suggestion is withheld (silent)."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    # Session 1: all 5 reps @ 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    # Session 2: set 3 only did 4 reps
    save_work_set(client, "left", 1, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 2, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 3, "40.0", "4", rpe="7.0", date="2026-07-03")

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is None


def test_rpe_trigger_ineligible_when_any_workset_missing_rpe(client):
    """When any working set is logged without RPE, session is ineligible (silent)."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    # Session 1: all RPE 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    # Session 2: set 3 has no RPE
    save_work_set(client, "left", 1, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 2, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 3, "40.0", "5", rpe=None, date="2026-07-03")

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is None


def test_rpe_trigger_ineligible_with_fewer_than_two_sessions(client):
    """Only 1 prior session -> ineligible / silent."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    page = worksets_page(client, date="2026-07-03")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is None


def test_per_hand_independence(client):
    """Left hand can be ready to progress while Right hand holds."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "40.0")

    # Left hand is easy (RPE 7.0); Right hand is hard (RPE 9.0)
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)
            save_work_set(client, "right", s, "40.0", "5", rpe="9.0", date=date)

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is not None
    assert "40.5" in autoreg_hint_text(page.text, "left")
    assert autoreg_hint_text(page.text, "right") is None


def test_deload_sessions_are_excluded_from_two_session_window(client):
    """Deload sessions are excluded when determining the last 2 sessions."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    # Session 1 (2026-07-01): non-deload, 40kg x 5 @ 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    # Session 2 (2026-07-03): DELOAD session with RPE 9.5
    for s in range(1, 4):
        save_work_set(client, "left", s, "30.0", "5", rpe="9.5", date="2026-07-03")
    client.post(
        "/session/update",
        data={"date": "2026-07-03", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )

    # Session 3 (2026-07-05): non-deload, 40kg x 5 @ 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-05")

    # Session 4 (2026-07-07): Window is Session 1 & 3 (Session 2 deload skipped) -> Ready!
    page = worksets_page(client, date="2026-07-07")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is not None
    assert "40.5" in autoreg_hint_text(page.text, "left")


def test_multi_session_days_count_as_distinct_sessions(client):
    """Two same-day sessions count as two distinct sessions for the 2-session window."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    # Morning session (session_number=1) on 2026-07-01
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01", session_number=1)

    # Evening session (session_number=2) on 2026-07-01
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01", session_number=2)

    # Next day 2026-07-02 -> Ready!
    page = worksets_page(client, date="2026-07-02")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is not None
    assert "40.5" in autoreg_hint_text(page.text, "left")


def test_progression_settings_target_reps_override_respected(client):
    """Autoregulation trigger respects combo-specific rep target."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    # Set combo rep target to 8 reps
    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "weight", "rep_min": 8, "rep_max": 8, "max_sets": 6},
    )

    # Log sets with 5 reps (under target 8)
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)

    page_miss = worksets_page(client, date="2026-07-05")
    assert autoreg_hint_text(page_miss.text, "left") is None

    # Now log sets with 8 reps @ RPE 7.0
    for date in ("2026-07-07", "2026-07-09"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "8", rpe="7.0", date=date)

    page_hit = worksets_page(client, date="2026-07-11")
    assert autoreg_hint_text(page_hit.text, "left") is not None


def test_custom_plate_inventory_increment_in_suggestion(client):
    """Suggestion computes increment according to user loadable ladder."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "20.0")

    # Clear small plates and set only 5.0kg plates
    client.post("/plates", data={"weight": "0.5", "count": 0})
    client.post("/plates", data={"weight": "1.25", "count": 0})
    client.post("/plates", data={"weight": "2.5", "count": 0})
    client.post("/plates", data={"weight": "5.0", "count": 6})
    client.post("/plates", data={"weight": "10.0", "count": 0})
    client.post("/plates", data={"weight": "20.0", "count": 0})

    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "20.0", "5", rpe="7.0", date=date)

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    hint = autoreg_hint_text(page.text, "left")
    assert hint is not None
    # Next loadable increment above 20.0 is 25.0
    assert "25" in hint


def test_set_progression_add_set_under_cap(client):
    """On Set progression path, when under max_sets cap and ready, suggests adding a set."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "set", "rep_min": 5, "rep_max": 5, "max_sets": 6},
    )

    # Log 2 sessions with 3 sets each @ 40kg x 5 @ RPE 7.0
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    hint = autoreg_hint_text(page.text, "left")
    assert hint is not None
    assert "add a set" in hint.lower() or "+1 set" in hint.lower()

    # Stepper values remain untouched at 40.0
    assert current_set_weight_input(page.text, "left") == "40.0"


def test_set_progression_at_cap_suggests_add_weight_and_reset_no_autoswitch(client):
    """On Set progression path, at max_sets cap, suggests adding weight and resetting to baseline sets,
    without auto-switching scheme."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "set", "rep_min": 5, "rep_max": 5, "max_sets": 6},
    )

    # Log 2 sessions with 6 sets each @ 40kg x 5 @ RPE 7.0 (at cap of 6)
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 7):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    hint = autoreg_hint_text(page.text, "left")
    assert hint is not None
    assert "add weight and reset to baseline sets" in hint.lower()

    # Stepper values remain untouched at 40.0
    assert current_set_weight_input(page.text, "left") == "40.0"

    # Verify no auto-switch: profile still shows path="set"
    prof_resp = client.get("/profile")
    assert prof_resp.status_code == 200
    assert 'value="set"' in prof_resp.text


def test_double_progression_rep_build_increments(client):
    """On Double progression path, rep-build phase suggests +1 rep across sessions until top of range."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # 2 sessions at baseline 40kg x 5 reps @ RPE 7.0
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)

    page1 = worksets_page(client, date="2026-07-05")
    assert page1.status_code == 200
    hint1 = autoreg_hint_text(page1.text, "left")
    assert hint1 is not None
    assert "+1 rep" in hint1
    assert "6" in hint1
    # Stepper values remain untouched
    assert current_set_weight_input(page1.text, "left") == "40.0"

    # Now log 2 sessions at 40kg x 6 reps @ RPE 7.0
    for date in ("2026-07-05", "2026-07-07"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "6", rpe="7.0", date=date)

    page2 = worksets_page(client, date="2026-07-09")
    assert page2.status_code == 200
    hint2 = autoreg_hint_text(page2.text, "left")
    assert hint2 is not None
    assert "+1 rep" in hint2
    assert "7" in hint2


def test_double_progression_advances_when_recent_sessions_differ(client):
    """Ready trigger fires on two non-deload sessions all at RPE <= 7 within
    range, even when they aren't identical — no stabilization gate. A user who
    self-bumped reps between the two sessions still gets the next nudge rather
    than being held for a confirmation session (#132, ADR-0011)."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # Two ready sessions that DIFFER: 40kg x 5, then a self-bumped 40kg x 6,
    # both @ RPE 7.0. The old stabilization gate would hold here (reps differ);
    # the spec trigger advances.
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "6", rpe="7.0", date="2026-07-03")

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    hint = autoreg_hint_text(page.text, "left")
    assert hint is not None
    assert "+1 rep" in hint
    assert "7" in hint
    # Still a passive hint — steppers untouched.
    assert current_set_weight_input(page.text, "left") == "40.0"


def test_double_progression_ceiling_transitions_to_weight_build(client):
    """When double progression reaches rep_max ceiling across 2 sessions, transitions to weight increment."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # 2 sessions at 40kg x 10 reps (rep_max) @ RPE 7.0
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "10", rpe="7.0", date=date)

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    hint = autoreg_hint_text(page.text, "left")
    assert hint is not None
    # Suggests adding one loadable increment (40.5 kg)
    assert "40.5" in hint
    assert "+0.5" in hint

    # Steppers remain untouched
    assert current_set_weight_input(page.text, "left") == "40.0"


def test_double_progression_weight_build_continues_above_min(client):
    """While in weight-build phase, suggestions continue to add loadable increments
    as long as reps stay above rep_min."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # 1) Top out at 40kg x 10 reps (2 sessions)
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "10", rpe="7.0", date=date)

    # 2) Advance to 40.5kg, perform 8 reps (> rep_min 5) @ RPE 7.0 for 2 sessions
    for date in ("2026-07-05", "2026-07-07"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.5", "8", rpe="7.0", date=date)

    page1 = worksets_page(client, date="2026-07-09")
    assert page1.status_code == 200
    hint1 = autoreg_hint_text(page1.text, "left")
    assert hint1 is not None
    # Still building weight: suggests 41.0 kg
    assert "41" in hint1
    assert "+0.5" in hint1

    # 3) Advance to 41.0kg, perform 6 reps (> rep_min 5) @ RPE 7.0 for 2 sessions
    for date in ("2026-07-09", "2026-07-11"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "41.0", "6", rpe="7.0", date=date)

    page2 = worksets_page(client, date="2026-07-13")
    assert page2.status_code == 200
    hint2 = autoreg_hint_text(page2.text, "left")
    assert hint2 is not None
    # Still building weight: suggests 41.25 kg (next loadable ladder rung)
    assert "41.25" in hint2
    assert "+0.25" in hint2


def test_double_progression_reset_to_baseline_when_reps_fall_to_min(client):
    """When reps fall to rep_min, that weight becomes the new baseline and double
    progression returns to rep-building phase."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # 1) Top out at 40kg x 10 reps (2 sessions)
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "10", rpe="7.0", date=date)

    # 2) Advance to 40.5kg, perform 8 reps @ RPE 7.0 for 2 sessions
    for date in ("2026-07-05", "2026-07-07"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.5", "8", rpe="7.0", date=date)

    # 3) Advance to 41.0kg, reps fall to rep_min (5 reps) @ RPE 7.0 for 2 sessions
    for date in ("2026-07-09", "2026-07-11"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "41.0", "5", rpe="7.0", date=date)

    page = worksets_page(client, date="2026-07-13")
    assert page.status_code == 200
    hint = autoreg_hint_text(page.text, "left")
    assert hint is not None
    # Reset to baseline: suggests building reps (+1 rep -> 6 reps) at current weight 41.0kg
    assert "+1 rep" in hint
    assert "6" in hint

    # Steppers remain untouched at 41.0
    assert current_set_weight_input(page.text, "left") == "41.0"


def test_double_progression_rpe_backstop_holds(client):
    """When RPE >= 9.0 occurs during double progression, suggestions hold (silent)."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # Session 1: 40kg x 5 @ RPE 7.0
    for s in range(1, 4):
        save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date="2026-07-01")

    # Session 2: set 3 was hard (RPE 9.0)
    save_work_set(client, "left", 1, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 2, "40.0", "5", rpe="7.0", date="2026-07-03")
    save_work_set(client, "left", 3, "40.0", "5", rpe="9.0", date="2026-07-03")

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    assert autoreg_hint_text(page.text, "left") is None


def test_double_progression_per_hand_independence(client):
    """Left hand and Right hand independently evaluate double progression phase and readiness."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # Left hand is easy (RPE 7.0), Right hand is straining (RPE 9.5)
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)
            save_work_set(client, "right", s, "40.0", "5", rpe="9.5", date=date)

    page = worksets_page(client, date="2026-07-05")
    assert page.status_code == 200
    left_hint = autoreg_hint_text(page.text, "left")
    right_hint = autoreg_hint_text(page.text, "right")

    assert left_hint is not None
    assert "+1 rep" in left_hint
    assert "6" in left_hint
    assert right_hint is None


def test_double_progression_derived_from_history_reflects_edits(client):
    """Phase and readiness are derived on the fly from history without stored state; edits immediately reflect."""
    register(client)
    gid = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40.0")

    client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "double", "rep_min": 5, "rep_max": 10, "max_sets": 6},
    )

    # 2 sessions at 40kg x 5 reps @ RPE 7.0
    for date in ("2026-07-01", "2026-07-03"):
        for s in range(1, 4):
            save_work_set(client, "left", s, "40.0", "5", rpe="7.0", date=date)

    # Ready to advance on 2026-07-05
    page1 = worksets_page(client, date="2026-07-05")
    assert autoreg_hint_text(page1.text, "left") is not None

    # Now edit set 3 on 2026-07-03 to RPE 9.5 (hard set)
    save_work_set(client, "left", 3, "40.0", "5", rpe="9.5", date="2026-07-03")

    # Immediately silent on reload
    page2 = worksets_page(client, date="2026-07-05")
    assert autoreg_hint_text(page2.text, "left") is None

    # Edit it back to RPE 6.5
    save_work_set(client, "left", 3, "40.0", "5", rpe="6.5", date="2026-07-03")

    # Immediately ready again
    page3 = worksets_page(client, date="2026-07-05")
    hint3 = autoreg_hint_text(page3.text, "left")
    assert hint3 is not None
    assert "+1 rep" in hint3
    assert "6" in hint3








