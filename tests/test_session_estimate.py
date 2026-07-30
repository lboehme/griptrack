"""SessionMaxEstimate: the per-session stand-in for CurrentMax on untested
(hand, grip, edge) combos — entered on the warmup page, feeding that hand's
ramp and work-set prefills for this session only (see CONTEXT.md)."""

import re

from tests.helpers import (
    current_set_field,
    get_session_page,
    grip_type_id,
    log_bodyweight,
    log_climb,
    log_max_test,
    login,
    register,
    register_second_user,
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


def estimate_form_hands(page_text):
    return set(re.findall(r'class="estimate-form" data-hand="(\w+)"', page_text))


def ramp_weights(page_text):
    """Parse warmup page into {(hand, step_index): suggested_weight}."""
    return {
        (h, int(s)): float(w)
        for h, s, w in re.findall(
            r'class="ramp-weight" data-hand="(\w+)" data-step="(\d+)">([\d.]+)<',
            page_text,
        )
    }


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


def test_fully_untested_combo_shows_an_estimate_form_per_hand_and_no_ramp(client):
    register(client)

    page = warmup_page(client)

    assert page.status_code == 200
    assert estimate_form_hands(page.text) == {"left", "right"}
    assert 'class="ramp-weight"' not in page.text
    # The guided-test link is pre-filled per hand with this page's context.
    grip_id = grip_type_id(client, "half crimp")
    for hand in ("left", "right"):
        assert (
            f'href="/max-tests/guided?grip_type_id={grip_id}&amp;edge_mm=20'
            f'&amp;date=2026-07-04&amp;hand={hand}"' in page.text
        )


def test_submitted_estimate_drives_that_hands_ramp_through_plate_rounding(client):
    register(client)

    response = save_estimate(client, "left", "42.5")
    assert response.status_code == 200

    page = warmup_page(client)
    # Same hand-computed values as the real-max ramp for 42.5 against the
    # seeded kg inventory (see test_warmup) — the estimate feeds the exact
    # same ramp/plate-rounding path.
    weights = ramp_weights(page.text)
    assert weights[("left", 0)] == 21.25
    assert weights[("left", 1)] == 27.5
    assert weights[("left", 2)] == 33.75
    assert weights[("left", 3)] == 38.0
    # The right hand still has neither max nor estimate: its form remains.
    assert estimate_form_hands(page.text) == {"right"}


def test_estimating_the_untested_hand_completes_a_mixed_ramp_table(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")

    save_estimate(client, "right", "40")

    page = warmup_page(client)
    weights = ramp_weights(page.text)
    # Both hands' ramps render together: the left from its real CurrentMax,
    # the right from the estimate (same literals as test_warmup's 42.5/40).
    assert weights[("left", 0)] == 21.25
    assert weights[("right", 0)] == 20.0
    assert weights[("right", 3)] == 36.0
    # A hand with a real CurrentMax is never shown an estimate prompt.
    assert estimate_form_hands(page.text) == set()


def test_resubmitting_an_estimate_updates_it_in_place(client):
    register(client)

    save_estimate(client, "left", "40")
    save_estimate(client, "left", "45")

    weights = ramp_weights(warmup_page(client).text)
    # The ramp follows the corrected value: 50% of 45 = 22.5 (20+2.5 exact),
    # not 40's first step of 20.0.
    assert weights[("left", 0)] == 22.5


def worksets_page(client, grip="half crimp", edge_mm=20, date="2026-07-04"):
    return get_session_page(
        client,
        "/session/worksets",
        {
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
        },
    ).text


def test_workset_prefill_uses_the_same_fallback_as_the_warmup_ramp(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    save_estimate(client, "right", "40")

    page = worksets_page(client)

    # Tested hand prefills its real CurrentMax; the untested hand prefills
    # the session's estimate — matching the ramp the user just saw. Set 1
    # is still the in-progress (current) set, so its raw prefill is what's
    # asserted against.
    assert current_set_field(page, "left", "weight") == "42.5"
    assert current_set_field(page, "right", "weight") == "40.0"


def test_worksets_from_an_estimate_only_combo_count_toward_volume(client):
    register(client)
    save_estimate(client, "left", "40")
    # Ordinary work sets, logged with no MaxWeightTest ever taken.
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    save_work_set(client, "left", 2, "40", "5", date="2026-07-04")

    page = client.get("/dashboard").text

    # 40x5 + 40x5 = 400, same TrainingVolume any tested combo would get.
    assert (
        'class="volume-point" data-combo="left|half crimp|20" '
        'data-date="2026-07-04" data-volume="400.0"' in page
    )


def test_estimate_only_training_never_feeds_the_strength_grade_correlation(client):
    """Mirrors test_correlation.seed_progression, but strength comes from
    estimates instead of MaxWeightTests — so no correlation may appear."""
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    for date, weight in (
        ("2026-06-01", "35"), ("2026-06-10", "42"), ("2026-06-20", "49")
    ):
        save_estimate(client, "left", weight, date=date)
        save_work_set(client, "left", 1, weight, "5", date=date)
    log_climb(client, "2026-06-02", "V2")
    log_climb(client, "2026-06-12", "V4")
    log_climb(client, "2026-06-22", "V6")

    page = client.get("/dashboard").text

    assert 'class="corr-r"' not in page
    assert 'class="corr-point"' not in page


def test_htmx_estimate_submission_gets_a_no_content_response(client):
    register(client)

    response = client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "left",
            "weight": "40",
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 204
    assert ("left", 0) in ramp_weights(warmup_page(client).text)


def test_a_new_session_never_inherits_an_earlier_sessions_estimate(client):
    register(client)
    save_estimate(client, "left", "40", date="2026-07-04")

    page = warmup_page(client, date="2026-07-11")

    # The combo is still untested, so the fresh session re-prompts.
    assert estimate_form_hands(page.text) == {"left", "right"}
    assert 'class="ramp-weight"' not in page.text


def test_estimate_above_the_weight_ceiling_is_rejected(client):
    register(client)

    response = save_estimate(client, "left", "1001")

    assert response.status_code == 422
    assert estimate_form_hands(warmup_page(client).text) == {"left", "right"}


def test_estimates_are_isolated_per_user(client):
    register(client)
    save_estimate(client, "left", "40")

    register_second_user(client)
    # Same date and combo: the second user sees no trace of the first's
    # estimate, and their own estimate is theirs alone.
    assert estimate_form_hands(warmup_page(client).text) == {"left", "right"}
    save_estimate(client, "left", "50")
    assert ramp_weights(warmup_page(client).text)[("left", 0)] == 25.0

    login(client, "lifter@example.com", "test-pw-1234")
    assert ramp_weights(warmup_page(client).text)[("left", 0)] == 20.0


def test_estimate_flow_under_sequential_hand_order(client):
    register(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    # One hand at a time: the default (left) page prompts for left only.
    assert estimate_form_hands(warmup_page(client).text) == {"left"}

    save_estimate(client, "left", "40")
    left = warmup_page(client)
    assert {h for h, s in ramp_weights(left.text)} == {"left"}
    assert estimate_form_hands(left.text) == set()

    right = warmup_page(client, hand="right")
    assert estimate_form_hands(right.text) == {"right"}
    save_estimate(client, "right", "42.5")
    assert {h for h, s in ramp_weights(warmup_page(client, hand="right").text)} == {
        "right"
    }
