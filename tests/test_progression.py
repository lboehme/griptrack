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
