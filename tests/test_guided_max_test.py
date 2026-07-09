"""Guided max test: the single-hand ladder routine that walks a user to a
real MaxWeightTest via a warmup + effort-rated working sets (issue #21,
PRD on issue #14). Entirely stateless server-side until "That's enough"."""

import re

from tests.helpers import (
    current_maxes,
    get_session_page,
    grip_type_id,
    log_bodyweight,
    login,
    register,
    register_second_user,
)


def default_estimate_value(page_text):
    match = re.search(r'name="estimate"[^>]*value="([\d.]+)"', page_text)
    return match.group(1)


def register_sequential(client, **kwargs):
    """Register and switch to sequential hand order — for tests that assert
    on the single-hand GET start-form shape, which alternating (#22) now
    renders differently (two estimate fields, not one)."""
    response = register(client, **kwargs)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    return response


HIDDEN_FIELD_RE = re.compile(r'<input type="hidden" name="(\w+)" value="([^"]*)">')


def hidden_fields(response):
    return dict(HIDDEN_FIELD_RE.findall(response.text))


def advance_step(client, response, actual, rating=None):
    data = hidden_fields(response)
    data["actual"] = actual
    if rating is not None:
        data["rating"] = rating
    return client.post("/max-tests/guided/step", data=data, follow_redirects=True)


def suggested_weight(response):
    match = re.search(r'<span class="suggested-weight">([\d.]+)</span>', response.text)
    return match.group(1)


def reach_working_set_one(client, warmup2_actual, rating, estimate="40"):
    """Drive the routine from the start through warmup set 2's rating,
    landing on working set 1's rendered suggestion."""
    first = start_guided_test(client, "left", estimate)
    second = advance_step(client, first, actual=suggested_weight(first))
    return advance_step(client, second, actual=str(warmup2_actual), rating=rating)


def guided_test_form(
    client, hand="left", grip="half crimp", edge_mm=20, date="2026-07-04"
):
    return client.get(
        "/max-tests/guided",
        params={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
        },
    )


def start_guided_test(
    client, hand, estimate, grip="half crimp", edge_mm=20, date="2026-07-04"
):
    return client.post(
        "/max-tests/guided",
        data={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "estimate": estimate,
        },
        follow_redirects=True,
    )


def test_starting_the_routine_renders_warmup_set_one_at_half_the_estimate(client):
    register(client)

    response = start_guided_test(client, "left", "42.5")

    assert response.status_code == 200
    assert 'data-kind="warmup"' in response.text
    assert 'data-set="1"' in response.text
    # 50% of 42.5 = 21.25, exact against the seeded kg plate inventory.
    assert '<span class="suggested-weight">21.25</span>' in response.text
    assert 'class="rating"' not in response.text


def test_start_form_prefills_estimate_from_bodyweight_when_logged(client):
    register_sequential(client)
    log_bodyweight(client, "2026-07-01", "80")

    page = guided_test_form(client).text

    # 50% of 80kg bodyweight is a sane starting estimate if unsure.
    assert default_estimate_value(page) == "40.0"


def test_start_form_falls_back_to_a_flat_estimate_with_no_bodyweight_on_file(client):
    register_sequential(client)

    page = guided_test_form(client).text

    # No BodyWeightLog at all: fall back to a flat, unit-appropriate default.
    assert default_estimate_value(page) == "10.0"


def test_start_form_falls_back_to_the_lbs_flat_estimate_for_lbs_users(client):
    register_sequential(client, unit_pref="lbs")

    page = guided_test_form(client).text

    assert default_estimate_value(page) == "20.0"


def test_continuing_from_warmup_set_one_reaches_warmup_set_two_unchanged(client):
    register(client)
    first = start_guided_test(client, "left", "42.5")

    second = advance_step(client, first, actual="21.25")

    assert second.status_code == 200
    assert 'data-kind="warmup"' in second.text
    assert 'data-set="2"' in second.text
    # Both warmup sets target the same fixed weight — never chained off
    # the first set's actual, only off the original estimate.
    assert '<span class="suggested-weight">21.25</span>' in second.text
    # Warmup set 2 is where the rating control first appears.
    assert 'class="rating"' in second.text


def test_each_effort_rating_produces_the_correctly_incremented_kg_suggestion(client):
    register(client)  # kg by default

    # kg ladder: effortless +10, fairly_easy +5, moderate +2, hard +1 —
    # actuals chosen so actual+increment lands on a whole multiple of 5,
    # exactly loadable from the seeded kg plates (20/10/5 alone cover any
    # multiple of 5), so the expected value is unambiguous.
    effortless = reach_working_set_one(client, 20, "effortless")
    assert 'data-kind="working"' in effortless.text
    assert 'data-set="1"' in effortless.text
    assert suggested_weight(effortless) == "30.0"

    fairly_easy = reach_working_set_one(client, 20, "fairly_easy")
    assert suggested_weight(fairly_easy) == "25.0"

    moderate = reach_working_set_one(client, 23, "moderate")
    assert suggested_weight(moderate) == "25.0"

    hard = reach_working_set_one(client, 24, "hard")
    assert suggested_weight(hard) == "25.0"


def test_each_effort_rating_produces_the_correctly_incremented_lbs_suggestion(client):
    register(client, unit_pref="lbs")

    # lbs ladder: effortless +20, fairly_easy +10, moderate +5, hard +2.5 —
    # same approach, using the seeded lbs plates (45/25/10/5 alone cover
    # these targets exactly).
    effortless = reach_working_set_one(client, 20, "effortless")
    assert suggested_weight(effortless) == "40.0"

    fairly_easy = reach_working_set_one(client, 20, "fairly_easy")
    assert suggested_weight(fairly_easy) == "30.0"

    moderate = reach_working_set_one(client, 20, "moderate")
    assert suggested_weight(moderate) == "25.0"

    hard = reach_working_set_one(client, 22.5, "hard")
    assert suggested_weight(hard) == "25.0"


def test_editing_the_actual_weight_before_rating_drives_the_next_suggestion(client):
    register(client)

    # Warmup's suggested weight for estimate=40 is 20.0kg; edit it up to 30
    # before rating "fairly_easy" (+5). If the edit were ignored in favor of
    # the original 20.0 suggestion, this would come out to 25.0, not 35.0.
    edited = reach_working_set_one(client, 30, "fairly_easy")

    assert suggested_weight(edited) == "35.0"


def test_rest_hint_shows_only_after_a_moderate_or_hard_rating(client):
    register(client)

    moderate = reach_working_set_one(client, 23, "moderate")
    assert 'class="rest-hint"' in moderate.text

    hard = reach_working_set_one(client, 24, "hard")
    assert 'class="rest-hint"' in hard.text

    effortless = reach_working_set_one(client, 20, "effortless")
    assert 'class="rest-hint"' not in effortless.text

    fairly_easy = reach_working_set_one(client, 20, "fairly_easy")
    assert 'class="rest-hint"' not in fairly_easy.text


def test_tapping_thats_enough_writes_exactly_one_max_weight_test(client):
    register(client)
    first = start_guided_test(client, "left", "40")
    second = advance_step(client, first, actual=suggested_weight(first))
    third = advance_step(client, second, actual="30", rating="fairly_easy")

    done = advance_step(client, third, actual="33", rating="enough")

    assert done.status_code == 200
    assert current_maxes(client) == {("left", "half crimp", 20): 33.0}


def test_abandoning_the_routine_never_tapping_enough_writes_nothing(client):
    register(client)
    first = start_guided_test(client, "left", "40")
    second = advance_step(client, first, actual=suggested_weight(first))
    advance_step(client, second, actual="30", rating="fairly_easy")

    assert current_maxes(client) == {}


def test_a_users_in_progress_state_cannot_write_another_users_max_test(client):
    register(client)  # user A: lifter@example.com
    first = start_guided_test(client, "left", "40")
    second = advance_step(client, first, actual=suggested_weight(first))
    # Capture user A's in-progress hidden state before switching accounts.
    carried_state = hidden_fields(second)

    register_second_user(client)  # now logged in as user B
    carried_state["actual"] = "33"
    carried_state["rating"] = "enough"
    response = client.post(
        "/max-tests/guided/step", data=carried_state, follow_redirects=True
    )

    assert response.status_code == 200
    # Written under the currently-authenticated user (B), never A.
    assert current_maxes(client) == {("left", "half crimp", 20): 33.0}
    login(client, "lifter@example.com", "test-pw-1234")
    assert current_maxes(client) == {}


def test_guided_routine_writes_nothing_to_session_max_estimate(client):
    register(client)
    first = start_guided_test(client, "left", "40", date="2026-07-04")
    advance_step(client, first, actual=suggested_weight(first))

    # The warmup page for the same combo/date must still prompt for an
    # estimate: the guided routine never touches SessionMaxEstimate storage.
    page = get_session_page(
        client,
        "/session/warmup",
        {
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "left",
        },
    ).text
    assert 'class="estimate-form" data-hand="left"' in page
    assert 'class="ramp-weight"' not in page


def test_guided_default_estimate_ignores_any_existing_session_max_estimate(client):
    register_sequential(client)
    client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "left",
            "weight": "55",
        },
        follow_redirects=True,
    )

    page = guided_test_form(client).text

    # The guided routine's default estimate is bodyweight-based (or a flat
    # fallback) only — never inherits an unrelated SessionMaxEstimate.
    assert default_estimate_value(page) == "10.0"


def test_an_unknown_hand_value_is_rejected(client):
    register(client)

    response = client.post(
        "/max-tests/guided",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "both",
            "estimate": "40",
        },
    )

    assert response.status_code == 400


def test_an_unknown_hand_value_is_rejected_on_the_start_form_too(client):
    register(client)

    response = guided_test_form(client, hand="both")

    assert response.status_code == 400


def test_omitting_the_rating_past_warmup_set_one_is_rejected(client):
    register(client)
    first = start_guided_test(client, "left", "40")
    second = advance_step(client, first, actual=suggested_weight(first))
    working_one = advance_step(
        client, second, actual="20", rating="fairly_easy"
    )

    # Working set 1 requires a rating — omitting it must not silently reset
    # the routine back to warmup set 2.
    response = advance_step(client, working_one, actual="25")

    assert response.status_code == 400


def test_an_unknown_rating_value_is_rejected(client):
    register(client)
    first = start_guided_test(client, "left", "40")

    response = advance_step(
        client, first, actual=suggested_weight(first), rating="excellent"
    )

    assert response.status_code == 400
