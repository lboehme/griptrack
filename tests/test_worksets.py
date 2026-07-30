import re

from tests.helpers import (
    completed_detail,
    current_maxes,
    current_set_field,
    get_session_page,
    grip_type_id,
    log_max_test,
    login,
    pill_text,
    register,
    register_second_user,
    save_focus_set,
    save_work_set,
)


def worksets_page(client, grip="half crimp", edge_mm=20, date="2026-07-04", hand=None):
    params = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
    }
    if hand is not None:
        params["hand"] = hand
    return get_session_page(client, "/session/worksets", params)


def setup_tested_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")


# ---------- POST /session/set (the Set commit, docs/adr/0007) ----------


def test_set_commit_writes_both_hands_in_one_atomic_request(client):
    setup_tested_user(client)

    response = save_focus_set(
        client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5")
    )
    assert response.status_code == 200

    detail = completed_detail(worksets_page(client).text, 1)
    assert "L 42.5 × 5 @ 8" in detail
    assert "R 40.0 × 5 @ 7.5" in detail


def test_invalid_partial_payload_writes_nothing_at_all(client):
    setup_tested_user(client)

    # Left is fully valid; right's weight is present but its reps are
    # missing. The whole request must be rejected -- including the
    # otherwise-valid left hand (ATOMIC: validate first).
    response = client.post(
        "/session/set",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "set_number": 1,
            "left_weight": "45",
            "left_reps": "5",
            "right_weight": "40.0",
        },
    )
    assert response.status_code == 400

    page = worksets_page(client).text
    assert completed_detail(page, 1) is None
    # The current set's left prefill is still the CurrentMax fallback
    # (42.5), not the rejected request's 45 -- nothing was written.
    assert current_set_field(page, "left", "weight") == "42.5"


def test_bad_rpe_is_rejected_and_writes_nothing(client):
    setup_tested_user(client)

    for bad_rpe in ("3.7", "0.5", "10.5"):
        response = client.post(
            "/session/set",
            data={
                "grip_type_id": grip_type_id(client, "half crimp"),
                "edge_mm": 20,
                "date": "2026-07-04",
                "set_number": 1,
                "left_weight": "42.5",
                "left_reps": "5",
                "left_rpe": bad_rpe,
            },
        )
        assert response.status_code == 400, bad_rpe

    assert completed_detail(worksets_page(client).text, 1) is None

    for good_rpe in ("1", "7.5", "10"):
        response = client.post(
            "/session/set",
            data={
                "grip_type_id": grip_type_id(client, "half crimp"),
                "edge_mm": 20,
                "date": "2026-07-04",
                "set_number": 1,
                "left_weight": "42.5",
                "left_reps": "5",
                "left_rpe": good_rpe,
            },
        )
        assert response.status_code == 200, good_rpe


def test_rpe_blank_persists_as_null(client):
    setup_tested_user(client)

    save_focus_set(client, 1, left=("42.5", "5", None), right=("40.0", "5", None))

    detail = completed_detail(worksets_page(client).text, 1)
    assert "@" not in detail


def test_reposting_the_same_session_hand_set_updates_in_place(client):
    setup_tested_user(client)

    save_focus_set(client, 1, left=("42.5", "5", "8"))
    save_focus_set(client, 1, left=("40.0", "4", "9"))

    page = worksets_page(client).text
    assert current_set_field(page, "left", "weight") == "40.0"
    assert current_set_field(page, "left", "reps") == "4"
    assert current_set_field(page, "left", "rpe") == "9.0"

    history = client.get("/history").text
    # Still one WorkSet for (left, set 1), not two.
    assert history.count('data-set="1"') == 1


def test_user_b_cannot_write_into_user_as_session(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7"))

    register_second_user(client)  # now logged in as user B
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "30")
    # Same date and set_number as user A's session -- must land in B's own
    # session, never touch A's.
    save_focus_set(client, 1, left=("30.0", "5", "6"))

    login(client, "lifter@example.com", "test-pw-1234")
    detail = completed_detail(worksets_page(client).text, 1)
    assert "L 42.5" in detail
    assert "L 30.0" not in detail


# ---------- /session/workset stays the per-hand primitive ----------


def test_per_hand_workset_endpoint_still_upserts_in_place(client):
    setup_tested_user(client)

    save_work_set(client, "left", 1, "42.5", "5", rpe="8.5")

    page = worksets_page(client).text
    assert current_set_field(page, "left", "weight") == "42.5"
    assert current_set_field(page, "left", "reps") == "5"
    assert current_set_field(page, "left", "rpe") == "8.5"

    save_work_set(client, "left", 1, "40.0", "4", rpe="9.0")
    page = worksets_page(client).text
    assert current_set_field(page, "left", "weight") == "40.0"


def test_an_accidentally_added_set_can_be_deleted(client):
    setup_tested_user(client)
    save_work_set(client, "left", 3, "42.5", "5")
    save_work_set(client, "left", 4, "30", "2")  # oops

    response = client.post(
        "/session/workset/delete",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "left",
            "set_number": 4,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    history = client.get("/history").text
    assert 'data-set="3"' in history
    assert 'data-set="4"' not in history


def test_current_max_rises_with_a_heavier_work_set_since_the_last_test(client):
    setup_tested_user(client)  # tested 2026-07-01 at 42.5 (L) / 40 (R)

    save_work_set(client, "left", 1, "45", "3", date="2026-07-04")

    combo = ("left", "half crimp", 20)
    assert current_maxes(client)[combo] == 45.0
    # The other hand is untouched by the left hand's work set.
    assert current_maxes(client)[("right", "half crimp", 20)] == 40.0

    # A newer max test supersedes: the heavy work set predates it.
    log_max_test(client, "left", "half crimp", 20, "2026-07-05", "41")
    assert current_maxes(client)[combo] == 41.0


def test_session_start_defaults_prefer_the_last_trained_combination(client):
    setup_tested_user(client)  # half crimp/20 tested 2026-07-01
    log_max_test(client, "left", "open hand", 10, "2026-07-02", "35")

    # Training happened on half crimp/20 after the open hand test.
    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-03")

    page = client.get("/session/new")
    grip_id = grip_type_id(client, "half crimp")
    assert f'value="{grip_id}" selected' in page.text
    assert 'name="edge_mm" value="20"' in page.text


# ---------- the Focus screen itself ----------


def test_worksets_page_renders_header_spine_hand_cards_and_ladder(client):
    setup_tested_user(client)

    page = worksets_page(client).text

    assert "focus-pill" in page
    assert pill_text(page) == "Set 1 of 3"  # protocol default_work_sets == 3
    assert page.count('class="progress-segment') == 3
    assert 'class="hand-card" data-hand="left"' in page
    assert 'class="hand-card" data-hand="right"' in page
    assert 'id="ladder-data"' in page
    assert current_set_field(page, "left", "weight") == "42.5"
    assert current_set_field(page, "right", "weight") == "40.0"
    assert current_set_field(page, "left", "reps") == "5"


def test_caption_shows_the_users_own_unit(client):
    register(client, unit_pref="lbs")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "90")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "85")

    page = worksets_page(client).text
    assert "lbs · plate-loadable" in page
    assert "kg · plate-loadable" not in page


def test_add_a_set_extends_the_denominator(client):
    setup_tested_user(client)

    page = worksets_page(client).text
    assert pill_text(page) == "Set 1 of 3"

    add_link = re.search(r'href="([^"]*sets=4[^"]*)"', page).group(1)
    extended = client.get(add_link.replace("&amp;", "&")).text
    assert pill_text(extended) == "Set 1 of 4"
    assert extended.count('class="progress-segment') == 4


def test_sequential_hand_order_shows_one_card_and_commits_one_hand(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    page = worksets_page(client).text
    assert page.count('class="hand-card"') == 1
    assert 'data-hand="left"' in page
    assert 'data-hand="right"' not in page

    response = save_focus_set(client, 1, left=("42.5", "5", "8"))
    assert response.status_code == 200

    page = worksets_page(client).text
    # A single-hand session uses the single-hand COMPLETED format -- no L/R
    # prefix, since there's only one hand in play.
    assert completed_detail(page, 1) == "42.5 kg × 5 @ 8.0"

    right = worksets_page(client, hand="right")
    assert 'data-hand="right"' in right.text
    assert 'data-hand="left"' not in right.text


def test_worksets_page_defaults_to_three_sets_with_protocol_prefills(client):
    setup_tested_user(client)

    page = worksets_page(client).text

    assert pill_text(page) == "Set 1 of 3"
    assert current_set_field(page, "left", "weight") == "42.5"
    assert current_set_field(page, "left", "reps") == "5"
    assert current_set_field(page, "right", "weight") == "40.0"


# ---------- session-level fields (notes/deload/pain) are unchanged ----------


def test_session_notes_over_the_length_ceiling_are_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    response = client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "x" * 2001},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422


def test_pain_report_note_over_the_length_ceiling_is_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    response = client.post(
        "/session/pain-report",
        data={
            "date": "2026-07-04",
            "hand": "left",
            "severity": "2",
            "note": "x" * 2001,
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422


def test_pain_report_with_an_invalid_hand_is_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    response = client.post(
        "/session/pain-report",
        data={
            "date": "2026-07-04",
            "hand": "left'; DROP TABLE users;--",
            "severity": "2",
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code in (400, 422)


def test_session_notes_and_deload_autosave(client):
    setup_tested_user(client)
    # Save a workset to ensure session is created
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    response = client.post(
        "/session/update",
        data={
            "date": "2026-07-04",
            "notes": "Felt tired today.",
            "is_deload": "on",
        },
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 204

    page = worksets_page(client, date="2026-07-04").text
    assert "Felt tired today." in page
    assert 'name="is_deload" checked' in page or 'checked name="is_deload"' in page


def test_pain_report_autosaves_and_displays(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    response = client.post(
        "/session/pain-report",
        data={
            "date": "2026-07-04",
            "hand": "left",
            "severity": "2",
            "note": "Tweaked a pulley",
        },
        headers={"HX-Request": "true"}
    )
    assert response.status_code == 204

    page = worksets_page(client, date="2026-07-04").text
    # Assert on values that only appear once the report actually exists —
    # not on strings like "left" or "2" that show up unconditionally
    # elsewhere on the page (hand dropdown, set numbers, etc.).
    assert "Tweaked a pulley" in page
    assert re.search(r"<td>left</td>\s*<td>2</td>", page)


def test_pain_report_save_is_an_upsert_keyed_on_hand(client):
    """The severity select and the note field each fire their own change
    event; one logical "tweak" report must still be one row, not two."""
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    # Severity posted first (as the severity-select's own change event would).
    client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "2"},
        headers={"HX-Request": "true"},
    )
    # Then the note posted separately (as the note field's own change event
    # would), same hand.
    response = client.post(
        "/session/pain-report",
        data={
            "date": "2026-07-04",
            "hand": "left",
            "severity": "2",
            "note": "Tweaked a pulley",
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204

    page = worksets_page(client, date="2026-07-04").text
    assert page.count("Tweaked a pulley") == 1
    assert page.count("<td>left</td>") == 1

    # A different hand still creates its own, independent row.
    client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "right", "severity": "1"},
        headers={"HX-Request": "true"},
    )
    page = worksets_page(client, date="2026-07-04").text
    assert page.count("<td>left</td>") == 1
    assert page.count("<td>right</td>") == 1


def test_pain_reports_and_session_meta_are_isolated_per_user(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    client.post(
        "/session/pain-report",
        data={
            "date": "2026-07-04",
            "hand": "left",
            "severity": "2",
            "note": "User A pulley tweak",
        },
        headers={"HX-Request": "true"},
    )
    client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "User A notes", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )

    register_second_user(client)  # now logged in as user B
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "35")
    save_work_set(client, "left", 1, "35", "5", date="2026-07-04")
    # Same date, from user B's client: user B's own session on this date
    # must not touch or expose user A's row.
    client.post(
        "/session/pain-report",
        data={
            "date": "2026-07-04",
            "hand": "left",
            "severity": "3",
            "note": "User B own tweak",
        },
        headers={"HX-Request": "true"},
    )
    client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "User B notes"},
        headers={"HX-Request": "true"},
    )
    b_page = worksets_page(client, date="2026-07-04").text
    assert "User B own tweak" in b_page
    assert "User A pulley tweak" not in b_page
    assert "User A notes" not in b_page

    login(client, "lifter@example.com", "test-pw-1234")
    a_page = worksets_page(client, date="2026-07-04").text
    assert "User A pulley tweak" in a_page
    assert "User A notes" in a_page
    assert 'name="is_deload" checked' in a_page or 'checked name="is_deload"' in a_page
    assert "User B own tweak" not in a_page
    assert "User B notes" not in a_page
