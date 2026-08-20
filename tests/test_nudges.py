"""HTTP-seam tests for session-start retest and estimate nudges (issue #130, ADR-0011)."""

import re

from tests.helpers import (
    get_session_page,
    grip_type_id,
    log_max_test,
    register,
    save_work_set,
)


def warmup_page(client, grip="half crimp", edge_mm=20, date="2026-07-04", hand=None):
    params = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
    }
    if hand is not None:
        params["hand"] = hand
    return get_session_page(client, "/session/warmup", params)


def worksets_page(client, grip="half crimp", edge_mm=20, date="2026-07-04", hand=None):
    params = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
    }
    if hand is not None:
        params["hand"] = hand
    return get_session_page(client, "/session/worksets", params)


def save_estimate(
    client, hand, weight, grip="half crimp", edge_mm=20, date="2026-07-04"
):
    return client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "weight": weight,
        },
        follow_redirects=True,
    )


def nudge_banner_type(page_text: str) -> str | None:
    match = re.search(r'class="[^"]*nudge-banner[^"]*"[^>]*data-nudge="([^"]+)"', page_text)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Retest Nudge Tests
# ---------------------------------------------------------------------------


def test_retest_nudge_fires_when_drift_ge_increment_and_ge_8_weeks(client):
    """Retest nudge fires when CurrentMax exceeds the last MaxWeightTest.weight
    by >= 1 loadable increment AND >= 8 weeks (56 days) have elapsed."""
    register(client)
    # Tested 40.0 kg on 2026-05-01
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40.0")

    # Log a heavier work set: 40.5 kg (drift is 0.5 kg, which is >= 1 loadable increment)
    save_work_set(client, "left", 1, "40.5", "5", date="2026-05-15")

    # Exactly 56 days (8 weeks) after test date 2026-05-01 -> 2026-06-26
    page = warmup_page(client, date="2026-06-26")
    assert page.status_code == 200
    assert nudge_banner_type(page.text) == "retest"
    assert "Current max" in page.text
    assert "guided" in page.text
    assert 'class="nudge-dismiss-btn"' in page.text


def test_retest_nudge_is_silent_under_8_weeks_regardless_of_drift(client):
    """Retest nudge remains silent if less than 8 weeks (56 days) have passed,
    even if there is large drift."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40.0")

    # Massive drift to 50.0 kg
    save_work_set(client, "left", 1, "50.0", "5", date="2026-05-15")

    # 55 days after test date 2026-05-01 -> 2026-06-25 (strictly under 8 weeks)
    page = warmup_page(client, date="2026-06-25")
    assert page.status_code == 200
    assert nudge_banner_type(page.text) is None


def test_retest_nudge_is_silent_when_drift_less_than_one_increment(client):
    """Retest nudge remains silent if >= 8 weeks have passed but CurrentMax has
    not drifted by at least one loadable increment above the last test."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40.0")

    # No heavier work set (CurrentMax is still 40.0 kg, drift = 0)
    # 70 days after test date (10 weeks)
    page = warmup_page(client, date="2026-07-10")
    assert page.status_code == 200
    assert nudge_banner_type(page.text) is None


def test_retest_nudge_clears_when_new_test_logged(client):
    """Logging a new MaxWeightTest resets the clock and clears the retest nudge."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40.0")
    save_work_set(client, "left", 1, "42.0", "5", date="2026-05-15")

    # Retest nudge fires on 2026-07-01 (61 days later)
    page1 = warmup_page(client, date="2026-07-01")
    assert nudge_banner_type(page1.text) == "retest"

    # User performs a new test on 2026-07-01
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.0")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "42.0")

    # Check warmup page again on 2026-07-01: nudge condition is now cleared
    page2 = warmup_page(client, date="2026-07-01")
    assert nudge_banner_type(page2.text) is None


# ---------------------------------------------------------------------------
# Estimate Nudge Tests
# ---------------------------------------------------------------------------


def test_estimate_nudge_fires_at_3_sessions_and_not_at_2(client):
    """Estimate nudge fires when a combo has NO MaxWeightTest but has accumulated
    SessionMaxEstimate across 3 distinct sessions (and does not fire at 2)."""
    register(client)

    # Session 1
    save_estimate(client, "left", "30.0", date="2026-07-01")
    save_estimate(client, "right", "30.0", date="2026-07-01")

    # Session 2
    save_estimate(client, "left", "30.0", date="2026-07-03")
    save_estimate(client, "right", "30.0", date="2026-07-03")

    # Warmup on date 2026-07-04: only 2 distinct session estimates exist -> no nudge
    page_after_2 = warmup_page(client, date="2026-07-04")
    assert nudge_banner_type(page_after_2.text) is None

    # Session 3
    save_estimate(client, "left", "30.0", date="2026-07-05")
    save_estimate(client, "right", "30.0", date="2026-07-05")

    # Warmup on date 2026-07-06: 3 distinct session estimates -> estimate nudge fires!
    page_after_3 = warmup_page(client, date="2026-07-06")
    assert nudge_banner_type(page_after_3.text) == "estimate"
    assert "3" in page_after_3.text
    assert "guided" in page_after_3.text
    assert 'class="nudge-dismiss-btn"' in page_after_3.text


def test_estimate_nudge_is_silent_once_a_real_test_exists(client):
    """Estimate nudge stays silent once a real MaxWeightTest exists for the combo."""
    register(client)

    # 3 sessions with estimates
    save_estimate(client, "left", "30.0", date="2026-07-01")
    save_estimate(client, "right", "30.0", date="2026-07-01")
    save_estimate(client, "left", "30.0", date="2026-07-03")
    save_estimate(client, "right", "30.0", date="2026-07-03")
    save_estimate(client, "left", "30.0", date="2026-07-05")
    save_estimate(client, "right", "30.0", date="2026-07-05")

    # Estimate nudge fires
    page = warmup_page(client, date="2026-07-06")
    assert nudge_banner_type(page.text) == "estimate"

    # User logs real MaxWeightTests
    log_max_test(client, "left", "half crimp", 20, "2026-07-06", "35.0")
    log_max_test(client, "right", "half crimp", 20, "2026-07-06", "35.0")

    # Estimate nudge must now be silent
    page_after_test = warmup_page(client, date="2026-07-06")
    assert nudge_banner_type(page_after_test.text) is None


# ---------------------------------------------------------------------------
# Priority & Interaction Tests
# ---------------------------------------------------------------------------


def test_retest_wins_over_estimate_when_both_qualify(client):
    """At most ONE banner: retest wins if both qualify for the combo."""
    register(client)

    # Left hand: has a test from 10 weeks ago and has drifted
    log_max_test(client, "left", "half crimp", 20, "2026-04-01", "30.0")
    save_work_set(client, "left", 1, "35.0", "5", date="2026-04-10")

    # Right hand: no test, but estimated across 3 sessions
    save_estimate(client, "right", "25.0", date="2026-06-01")
    save_estimate(client, "right", "25.0", date="2026-06-05")
    save_estimate(client, "right", "25.0", date="2026-06-10")

    # Warmup on 2026-07-01: Left qualifies for retest, Right qualifies for estimate
    page = warmup_page(client, date="2026-07-01")
    assert page.status_code == 200
    # Retest banner must win
    assert nudge_banner_type(page.text) == "retest"
    # Ensure there is exactly ONE nudge banner
    assert len(re.findall(r'class="[^"]*nudge-banner[^"]*"', page.text)) == 1


def test_nudge_renders_on_worksets_page(client):
    """Session-start nudge also renders on the worksets page."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40.0")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40.0")
    save_work_set(client, "left", 1, "41.0", "5", date="2026-05-15")

    page = worksets_page(client, date="2026-07-01")
    assert page.status_code == 200
    assert nudge_banner_type(page.text) == "retest"


def test_sequential_hand_mode_evaluates_selected_hand(client):
    """In sequential hand mode, only the selected hand is evaluated."""
    register(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    # Left hand has a test from 10 weeks ago with drift
    log_max_test(client, "left", "half crimp", 20, "2026-04-01", "40.0")
    save_work_set(client, "left", 1, "42.0", "5", date="2026-04-15")

    # Right hand has a recent test with no drift
    log_max_test(client, "right", "half crimp", 20, "2026-06-20", "40.0")

    # Viewing left hand -> retest nudge appears
    page_left = warmup_page(client, hand="left", date="2026-07-01")
    assert nudge_banner_type(page_left.text) == "retest"

    # Viewing right hand -> no nudge
    page_right = warmup_page(client, hand="right", date="2026-07-01")
    assert nudge_banner_type(page_right.text) is None


def test_voided_test_is_ignored_by_retest_and_estimate_nudges(client):
    """Voided tests are excluded from CurrentMax and max test lookups."""
    register(client)

    # 3 sessions with estimates
    save_estimate(client, "left", "30.0", date="2026-07-01")
    save_estimate(client, "right", "30.0", date="2026-07-01")
    save_estimate(client, "left", "30.0", date="2026-07-03")
    save_estimate(client, "right", "30.0", date="2026-07-03")
    save_estimate(client, "left", "30.0", date="2026-07-05")
    save_estimate(client, "right", "30.0", date="2026-07-05")

    # Log a max test, which silences estimate nudge
    log_max_test(client, "left", "half crimp", 20, "2026-07-06", "35.0")
    log_max_test(client, "right", "half crimp", 20, "2026-07-06", "35.0")
    assert nudge_banner_type(warmup_page(client, date="2026-07-06").text) is None

    # Void the left test via POST /max-tests/{id}/void
    page = client.get("/max-tests")
    for test_id in re.findall(r'action="/max-tests/(\d+)/void"', page.text):
        client.post(f"/max-tests/{test_id}/void", follow_redirects=True)

    # For sequential left hand, combo is back to untested with 3 estimates -> estimate nudge fires again!
    client.post("/profile", data={"hand_order_pref": "sequential"})
    page = warmup_page(client, hand="left", date="2026-07-06")
    assert nudge_banner_type(page.text) == "estimate"


def test_multi_session_day_estimates_count_as_distinct_sessions(client):
    """Two same-day sessions count as two distinct sessions for the 3-session estimate threshold."""
    register(client)

    # Session 1 on 2026-07-01 (session_number 1)
    client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-01",
            "session_number": 1,
            "hand": "left",
            "weight": "30.0",
        },
    )

    # Session 2 on 2026-07-01 (session_number 2)
    client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-01",
            "session_number": 2,
            "hand": "left",
            "weight": "30.0",
        },
    )

    # Only 2 distinct sessions so far -> no nudge
    page_after_2 = warmup_page(client, date="2026-07-02")
    assert nudge_banner_type(page_after_2.text) is None

    # Session 3 on 2026-07-03
    client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-03",
            "session_number": 1,
            "hand": "left",
            "weight": "30.0",
        },
    )

    # Now 3 distinct sessions have estimates -> estimate nudge fires!
    page_after_3 = warmup_page(client, date="2026-07-04")
    assert nudge_banner_type(page_after_3.text) == "estimate"


def test_retest_nudge_respects_custom_plate_inventory_increment(client):
    """Retest drift threshold uses the user's actual loadable ladder increment."""
    register(client)

    # Clear default small plates and set only 5kg plates
    client.post("/plates", data={"weight": "0.5", "count": 0})
    client.post("/plates", data={"weight": "1.25", "count": 0})
    client.post("/plates", data={"weight": "2.5", "count": 0})
    client.post("/plates", data={"weight": "5.0", "count": 6})
    client.post("/plates", data={"weight": "10.0", "count": 0})
    client.post("/plates", data={"weight": "20.0", "count": 0})

    # Test is 20.0 kg on 2026-04-01
    log_max_test(client, "left", "half crimp", 20, "2026-04-01", "20.0")
    log_max_test(client, "right", "half crimp", 20, "2026-04-01", "20.0")

    # Work set is 22.0 kg (drift is 2.0 kg, which is less than the 5.0 kg loadable increment)
    save_work_set(client, "left", 1, "22.0", "5", date="2026-04-15")

    # >= 8 weeks pass (70 days later)
    page_sub_increment = warmup_page(client, date="2026-06-10")
    assert nudge_banner_type(page_sub_increment.text) is None

    # Now log a work set at 25.0 kg (drift 5.0 kg >= 5.0 kg increment)
    save_work_set(client, "left", 2, "25.0", "5", date="2026-04-16")
    page_at_increment = warmup_page(client, date="2026-06-10")
    assert nudge_banner_type(page_at_increment.text) == "retest"
