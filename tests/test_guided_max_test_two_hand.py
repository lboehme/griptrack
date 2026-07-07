"""Guided max test: two-hand interleaved execution (issue #22, PRD on #14).
Builds on #21's single-hand ladder mechanics (tests/test_guided_max_test.py)
without changing them — this only covers running two independent ladders
within one routine, per the user's existing hand_order_pref."""

import re

from tests.helpers import current_maxes, grip_type_id, login, register, register_second_user


def alternating_start_form(
    client, grip="half crimp", edge_mm=20, date="2026-07-04"
):
    return client.get(
        "/max-tests/guided",
        params={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
        },
    )


def test_alternating_start_form_shows_an_estimate_input_per_hand(client):
    register(client)  # default hand_order_pref is alternating

    page = alternating_start_form(client).text

    assert re.search(r'name="left_estimate"[^>]*value="10.0"', page)
    assert re.search(r'name="right_estimate"[^>]*value="10.0"', page)
    assert 'action="/max-tests/guided/both"' in page


def start_both(client, left_estimate, right_estimate, grip="half crimp", edge_mm=20, date="2026-07-04"):
    return client.post(
        "/max-tests/guided/both",
        data={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "left_estimate": left_estimate,
            "right_estimate": right_estimate,
        },
        follow_redirects=True,
    )


def suggested_weights(response):
    return {
        hand: float(weight)
        for hand, weight in re.findall(
            r'class="suggested-weight" data-hand="(\w+)">([\d.]+)<', response.text
        )
    }


HIDDEN_FIELD_RE = re.compile(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">')


def hand_block(response, hand):
    """The one card <div>...</div> for a hand — works whether that hand is
    still active (contains a <form>) or already done (a plain notice), since
    neither branch nests another <div> before the card's own closing tag."""
    match = re.search(
        rf'<div class="card" data-hand="{hand}".*?</div>',
        response.text,
        re.DOTALL,
    )
    return match.group(0)


def hidden_fields_for(response, hand):
    return dict(HIDDEN_FIELD_RE.findall(hand_block(response, hand)))


def advance_hand(client, response, hand, actual, rating=None):
    data = hidden_fields_for(response, hand)
    data["actual"] = actual
    if rating is not None:
        data["rating"] = rating
    return client.post("/max-tests/guided/step", data=data, follow_redirects=True)


def continue_hand(client, response, hand):
    """Confirm a hand's currently-suggested weight with no rating — the
    warmup-set-1-to-2 transition, the only ratingless step."""
    return advance_hand(
        client, response, hand, actual=str(suggested_weights(response)[hand])
    )


def test_starting_both_hands_shows_independent_warmup_set_one_for_each(client):
    register(client)

    response = start_both(client, "42.5", "40")

    assert response.status_code == 200
    assert 'data-hand="left"' in response.text
    assert 'data-hand="right"' in response.text
    weights = suggested_weights(response)
    # 50% of each hand's own estimate — independently derived.
    assert weights["left"] == 21.25
    assert weights["right"] == 20.0


def test_advancing_one_hand_leaves_the_others_state_unchanged(client):
    register(client)
    first = start_both(client, "42.5", "40")

    # Left continues from warmup set 1 to warmup set 2 (no rating yet);
    # right's form is never touched.
    second = advance_hand(client, first, "left", actual="21.25")

    assert 'data-hand="left" data-kind="warmup" data-set="2"' in second.text
    assert 'data-hand="right" data-kind="warmup" data-set="1"' in second.text
    weights = suggested_weights(second)
    assert weights["left"] == 21.25
    assert weights["right"] == 20.0
    # Left (warmup set 2) now has the rating control; right (still set 1) doesn't.
    assert 'class="rating"' in hand_block(second, "left")
    assert 'class="rating"' not in hand_block(second, "right")


def test_rating_one_hand_never_changes_the_others_suggestion(client):
    register(client)
    page = start_both(client, "42.5", "40")
    page = continue_hand(client, page, "left")
    page = continue_hand(client, page, "right")

    # Rate left "hard" (+1kg) on warmup set 2 -> left's working set 1 = 25.0.
    page = advance_hand(client, page, "left", actual="24", rating="hard")
    weights = suggested_weights(page)
    assert weights["left"] == 25.0
    assert weights["right"] == 20.0  # untouched — right's own warmup set 2

    # Rate right "effortless" (+10kg) -> right's working set 1 = 30.0, left
    # (already on its own working set 1) stays exactly where it was.
    page = advance_hand(client, page, "right", actual="20", rating="effortless")
    weights = suggested_weights(page)
    assert weights["right"] == 30.0
    assert weights["left"] == 25.0


def test_ending_one_hand_writes_its_test_and_leaves_the_other_live(client):
    register(client)
    page = start_both(client, "42.5", "40")
    page = continue_hand(client, page, "left")
    page = continue_hand(client, page, "right")

    page = advance_hand(client, page, "left", actual="22", rating="enough")

    assert "Recorded" in hand_block(page, "left")
    assert "22.0" in hand_block(page, "left")
    # Right's ladder is untouched and still live (still on warmup set 2).
    assert 'data-hand="right" data-kind="warmup" data-set="2"' in page.text
    assert current_maxes(client) == {("left", "half crimp", 20): 22.0}


def test_running_both_hands_to_completion_produces_two_independent_rows(client):
    register(client)
    page = start_both(client, "42.5", "40")
    page = continue_hand(client, page, "left")
    page = continue_hand(client, page, "right")
    page = advance_hand(client, page, "left", actual="22", rating="enough")
    page = advance_hand(client, page, "right", actual="21", rating="enough")

    assert current_maxes(client) == {
        ("left", "half crimp", 20): 22.0,
        ("right", "half crimp", 20): 21.0,
    }


def test_ending_only_one_hand_and_abandoning_the_other_writes_one_row(client):
    register(client)
    page = start_both(client, "42.5", "40")
    page = continue_hand(client, page, "left")
    page = continue_hand(client, page, "right")
    advance_hand(client, page, "left", actual="22", rating="enough")
    # Right is simply never finished — no "enough" tap.

    assert current_maxes(client) == {("left", "half crimp", 20): 22.0}


def test_per_user_isolation_holds_for_the_two_hand_flow(client):
    register(client)  # user A
    page = start_both(client, "42.5", "40")
    page = continue_hand(client, page, "left")
    carried_state = hidden_fields_for(page, "left")

    register_second_user(client)  # now logged in as user B
    carried_state["actual"] = "22"
    carried_state["rating"] = "enough"
    response = client.post(
        "/max-tests/guided/step", data=carried_state, follow_redirects=True
    )

    assert response.status_code == 200
    assert current_maxes(client) == {("left", "half crimp", 20): 22.0}
    login(client, "lifter@example.com", "test-pw-1234")
    assert current_maxes(client) == {}


def start_single(client, hand, estimate, grip="half crimp", edge_mm=20, date="2026-07-04"):
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


def advance_single(client, response, actual, rating=None):
    data = dict(HIDDEN_FIELD_RE.findall(response.text))
    data["actual"] = actual
    if rating is not None:
        data["rating"] = rating
    return client.post("/max-tests/guided/step", data=data, follow_redirects=True)


def single_suggested_weight(response):
    match = re.search(r'<span class="suggested-weight">([\d.]+)</span>', response.text)
    return match.group(1)


def test_sequential_done_page_links_to_start_the_other_hand(client):
    register(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    first = start_single(client, "left", "40")
    second = advance_single(client, first, actual=single_suggested_weight(first))
    done = advance_single(client, second, actual="22", rating="enough")

    assert 'href="/max-tests/guided?' in done.text
    assert "hand=right" in done.text
