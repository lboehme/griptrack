"""Set 1 of a session starts at Today's plan (PR #154 review, owner
decision D1; MUST-FIX 2). When a hand has no saved set in this session yet,
session play pre-fills set 1 with exactly the per-hand weight (and reps)
Today's plan shows -- suggestion, else last session's top weight, else
CurrentMax, with Go lighter's 85% round-down. Carry-down from the previous
set in this session still wins for sets 2+."""

import pytest

from tests.helpers import (
    complete_warmup,
    current_set_field,
    grip_type_id,
    log_max_test,
    register,
    save_focus_set,
)
from tests.test_today import TODAY, day, full_session, hand_plan, plan_attr, tested_user, today_page


def play_set_one(client, **extra):
    gid = grip_type_id(client, "half crimp")
    page = complete_warmup(client, gid, 20, date=TODAY.isoformat(), **extra)
    return page.text


def assert_play_matches_today(client, expected_weight, expected_source):
    page = today_page(client)
    for hand in ("left", "right"):
        assert hand_plan(page, hand) == (expected_weight, expected_source)
    reps = plan_attr(page, "reps")

    play = play_set_one(client)
    for hand in ("left", "right"):
        assert float(current_set_field(play, hand, "weight")) == float(expected_weight)
        assert current_set_field(play, hand, "reps") == reps


def test_set_one_starts_at_the_autoregulation_suggestion(client):
    tested_user(client)
    full_session(client, day(-8), weight=40.0, rpe=7.0)
    full_session(client, day(-5), weight=40.0, rpe=7.0)

    assert_play_matches_today(client, "40.5", "suggestion")


def test_set_one_starts_at_the_last_sessions_top_weight(client):
    tested_user(client)
    full_session(client, day(-5), weight=37.5)

    assert_play_matches_today(client, "37.5", "last")


def test_set_one_starts_at_current_max_with_no_history(client):
    tested_user(client, weight="40")

    assert_play_matches_today(client, "40.0", "max")


def test_set_one_starts_at_the_go_lighter_weight(client):
    tested_user(client, weight="40")
    client.post("/today/lighter", data={"date": TODAY.isoformat(), "on": "1"})

    assert_play_matches_today(client, "33.75", "max")


def test_reviewer_repro_tweak_then_go_lighter_prefills_the_lighter_weight(client):
    """Max 40, last session at 30, a tweak today, Go lighter: Today shows
    25.5 and play must pre-fill 25.5 -- not 40 (the safety-relevant flow
    offered after a pain report)."""
    tested_user(client, weight="40")
    full_session(client, day(-3), weight=30.0)
    client.post(
        "/log/tweak",
        data={"date": TODAY.isoformat(), "hand": "left", "severity": "2"},
    )
    client.post("/today/lighter", data={"date": TODAY.isoformat(), "on": "1"})

    assert_play_matches_today(client, "25.5", "last")


def test_set_one_reps_follow_the_plan_on_double_progression(client):
    tested_user(client)
    client.post(
        "/profile/progression",
        data={"path": "double", "rep_min": 3, "rep_max": 8, "max_sets": 6},
    )
    full_session(client, day(-5), weight=37.5, reps=4)

    page = today_page(client)
    assert plan_attr(page, "reps") == "4"
    play = play_set_one(client)
    assert current_set_field(play, "left", "reps") == "4"


def test_carry_down_still_wins_for_set_two(client):
    tested_user(client, weight="40")
    play_set_one(client)
    save_focus_set(client, 1, date=TODAY.isoformat(), left=(35, 6, 8), right=(34, 6, 8))
    gid = grip_type_id(client, "half crimp")
    client.post(
        "/session/rest/end", data={"grip_type_id": gid, "edge_mm": 20, "date": TODAY.isoformat()}
    )

    play = play_set_one(client)
    assert current_set_field(play, "left", "weight") == "35.0"
    assert current_set_field(play, "right", "weight") == "34.0"
    assert current_set_field(play, "left", "reps") == "6"


@pytest.mark.parametrize("hand_order", ["sequential"])
def test_sequential_other_hand_also_starts_at_the_plan(client, hand_order):
    register(client)
    log_max_test(client, "left", "half crimp", 20, day(-60), "40")
    log_max_test(client, "right", "half crimp", 20, day(-60), "36")
    full_session(client, day(-5), weight=30.0)
    client.post("/profile", data={"hand_order_pref": hand_order})

    left = play_set_one(client, hand="left")
    assert current_set_field(left, "left", "weight") == "30.0"
    save_focus_set(client, 1, date=TODAY.isoformat(), left=(32, 5, 7))
    gid = grip_type_id(client, "half crimp")
    client.post(
        "/session/rest/end", data={"grip_type_id": gid, "edge_mm": 20, "date": TODAY.isoformat()}
    )
    right = play_set_one(client, hand="right")
    assert current_set_field(right, "right", "weight") == "30.0"
