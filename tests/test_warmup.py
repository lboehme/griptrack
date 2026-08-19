import re
from datetime import date as date_type

from tests.helpers import get_session_page, grip_type_id, log_max_test, register


def warmup_page(client, grip="half crimp", edge_mm=20, date="2026-07-04"):
    return get_session_page(
        client,
        "/session/warmup",
        {
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
        },
    )


def ramp_weights(page_text):
    """Parse warmup page into {(hand, step_index): suggested_weight}."""
    return {
        (h, int(s)): float(w)
        for h, s, w in re.findall(
            r'class="ramp-weight" data-hand="(\w+)" data-step="(\d+)">([\d.]+)<',
            page_text,
        )
    }


def test_ramp_is_percent_of_current_max_rounded_down_to_loadable(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    weights = ramp_weights(warmup_page(client).text)

    # Hand-computed against the seeded kg inventory
    # (0.5x2, 1.25x2, 2.5x2, 5x2, 10x2, 20x1), rounding down to the
    # closest loadable stack: 50/65/80/90% of max.
    assert weights[("left", 0)] == 21.25   # 21.25 exact (20+1.25)
    assert weights[("left", 1)] == 27.5    # target 27.625
    assert weights[("left", 2)] == 33.75   # target 34.0
    assert weights[("left", 3)] == 38.0    # target 38.25
    assert weights[("right", 0)] == 20.0   # 20 exact (the 20 plate)
    assert weights[("right", 1)] == 26.0   # 26 exact (20+5+0.5+0.5)
    assert weights[("right", 2)] == 31.75  # target 32.0
    assert weights[("right", 3)] == 36.0   # 36 exact (20+10+5+0.5+0.5)


def clear_inventory(client):
    rows = re.findall(
        r'class="plate-weight">([^<]+)<', client.get("/plates").text
    )
    for weight in rows:
        client.post("/plates", data={"weight": weight, "count": "0"})


def test_empty_plate_inventory_suggests_zero_for_every_step(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    clear_inventory(client)

    weights = ramp_weights(warmup_page(client).text)

    assert set(weights.values()) == {0.0}


def test_target_below_smallest_loadable_increment_suggests_zero(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "15")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "15")
    clear_inventory(client)
    client.post("/plates", data={"weight": "20", "count": "1"})

    weights = ramp_weights(warmup_page(client).text)

    # Every ramp target (7.5 .. 13.5) is below the only plate owned.
    assert set(weights.values()) == {0.0}


def test_sequential_hand_order_shows_one_hand_at_a_time(client):
    register(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    first = warmup_page(client)
    assert {hand for hand, step in ramp_weights(first.text)} == {"left"}

    second = client.get(
        "/session/warmup",
        params={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "right",
        },
    )
    assert {hand for hand, step in ramp_weights(second.text)} == {"right"}


def checked_steps(page_text):
    return {
        (h, int(s))
        for h, s, attrs in re.findall(
            r'class="step-check" data-hand="(\w+)" data-step="(\d+)"([^>]*)>',
            page_text,
        )
        if "checked" in attrs
    }


def check_step(client, hand, step, grip="half crimp", edge_mm=20, date="2026-07-04"):
    return client.post(
        "/session/check",
        data={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "step_index": step,
        },
        follow_redirects=True,
    )


def test_checking_a_warmup_step_autosaves_and_starts_the_session(client):
    """Implicit create-on-first-tap: only guaranteed for TODAY (a past
    date instead requires the explicit confirm prompt — see
    test_multi_session_days.py)."""
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    today = date_type.today().isoformat()

    before = warmup_page(client, date=today)
    assert 'class="session-started"' not in before.text
    assert checked_steps(before.text) == set()

    check_step(client, "left", 0, date=today)

    # A fresh fetch (no client state) must show the persisted progress and
    # the session that came into existence on that first tap.
    after = warmup_page(client, date=today)
    assert 'class="session-started"' in after.text
    assert checked_steps(after.text) == {("left", 0)}

    check_step(client, "right", 0, date=today)
    check_step(client, "left", 1, date=today)
    assert checked_steps(warmup_page(client, date=today).text) == {
        ("left", 0),
        ("right", 0),
        ("left", 1),
    }


def test_unchecking_a_warmup_step_persists_too(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    check_step(client, "left", 0)
    assert checked_steps(warmup_page(client).text) == {("left", 0)}

    # The same action on a checked step unchecks it (accidental tap).
    check_step(client, "left", 0)
    assert checked_steps(warmup_page(client).text) == set()


def test_session_start_page_lists_previous_sessions(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    check_step(client, "left", 0, date="2026-07-04")

    page = client.get("/session/new").text

    assert 'class="history-session" data-date="2026-07-04"' in page


def test_session_start_form_defaults_to_the_last_used_combination(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "left", "open hand", 10, "2026-07-02", "35")

    page = client.get("/session/new")

    assert page.status_code == 200
    # The most recently used grip/edge is preselected.
    grip_id = grip_type_id(client, "open hand")
    assert f'value="{grip_id}" selected' in page.text
    assert 'name="edge_mm" value="10"' in page.text


def test_warmup_renders_header_spine_with_step_pill_and_bar(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    page = warmup_page(client).text

    assert '<span class="focus-pill">' in page
    assert "Step" in page and "of" in page
    assert re.search(r'Step\s*<span class="focus-pill-n">1</span>\s*of\s*'
                      r'<span class="focus-pill-m">4</span>', page)
    assert 'class="focus-progress-bar"' in page
    assert page.count('class="progress-segment') == 4


def test_warmup_step_pill_reflects_first_incomplete_step(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    check_step(client, "left", 0)
    check_step(client, "right", 0)
    # Step 0 (index) is fully ticked for both hands -> now on step 2 (index 1).
    page = warmup_page(client).text

    assert re.search(r'Step\s*<span class="focus-pill-n">2</span>\s*of\s*'
                      r'<span class="focus-pill-m">4</span>', page)


def test_warmup_renders_one_card_per_ramp_step(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    page = warmup_page(client).text

    assert page.count('class="card ramp-card"') == 4
    # Each card shows its ramp percentage.
    for pct in ("50%", "65%", "80%", "90%"):
        assert f'class="ramp-card-percent">{pct}<' in page
    # And, inside those cards, the same L/R tick targets tested elsewhere.
    assert ramp_weights(page)
    assert checked_steps(page) == set()


def test_sequential_hand_order_ramp_card_is_a_single_column(client):
    register(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    page = warmup_page(client).text

    assert "ramp-card-hands-single" in page
    # Only the left hand's tick target renders per card (one column).
    assert {hand for hand, step in ramp_weights(page)} == {"left"}


def test_one_untested_hand_still_renders_the_tested_hands_ramp(client):
    register(client)
    # Only the left hand is tested; the right hand has no max for this combo.
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")

    page = warmup_page(client)

    assert page.status_code == 200
    # The untested hand is prompted (guided test or a session estimate) ...
    grip_id = grip_type_id(client, "half crimp")
    assert (
        f'href="/max-tests/guided?grip_type_id={grip_id}&amp;edge_mm=20'
        f'&amp;date=2026-07-04&amp;hand=right"' in page.text
    )
    assert 'class="estimate-form" data-hand="right"' in page.text
    # ... while the tested hand's ramp renders normally, not blanked.
    assert {hand for hand, step in ramp_weights(page.text)} == {"left"}
