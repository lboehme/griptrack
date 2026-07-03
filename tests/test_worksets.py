import re

from tests.helpers import current_maxes, grip_type_id, log_max_test, register


def worksets_page(client, grip="half crimp", edge_mm=20, date="2026-07-04", hand=None):
    params = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
    }
    if hand is not None:
        params["hand"] = hand
    return client.get("/session/worksets", params=params)


def workset_rows(page_text):
    """Parse the page into {(hand, set_number): (weight, reps, rpe)} strings."""
    rows = {}
    for hand, set_number, block in re.findall(
        r'<td class="workset-cell" data-hand="(\w+)" data-set="(\d+)">(.*?)</td>',
        page_text,
        re.DOTALL,
    ):
        weight = re.search(r'name="weight" value="([^"]*)"', block).group(1)
        reps = re.search(r'name="reps" value="([^"]*)"', block).group(1)
        rpe = re.search(r'name="rpe" value="([^"]*)"', block).group(1)
        rows[(hand, int(set_number))] = (weight, reps, rpe)
    return rows


def setup_tested_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")


def save_work_set(
    client, hand, set_number, weight, reps, rpe=None,
    grip="half crimp", edge_mm=20, date="2026-07-04",
):
    data = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
        "hand": hand,
        "set_number": set_number,
        "weight": weight,
        "reps": reps,
    }
    if rpe is not None:
        data["rpe"] = rpe
    return client.post("/session/workset", data=data, follow_redirects=True)


def test_each_saved_work_set_persists_and_can_be_edited(client):
    setup_tested_user(client)

    save_work_set(client, "left", 1, "42.5", "5", rpe="8.5")

    rows = workset_rows(worksets_page(client).text)
    assert rows[("left", 1)] == ("42.5", "5", "8.5")
    # Untouched cells keep their prefills.
    assert rows[("left", 2)] == ("42.5", "5", "")

    # Editing the same cell updates it rather than duplicating the set.
    save_work_set(client, "left", 1, "40.0", "4", rpe="9.0")
    rows = workset_rows(worksets_page(client).text)
    assert rows[("left", 1)] == ("40.0", "4", "9.0")


def test_add_another_set_extends_the_table_and_saved_sets_stay(client):
    setup_tested_user(client)

    page = worksets_page(client)
    add_link = re.search(r'href="([^"]*sets=4[^"]*)"', page.text).group(1)
    extended = client.get(add_link.replace("&amp;", "&"))
    assert ("left", 4) in workset_rows(extended.text)

    # An unsaved extra row can be dismissed without saving it first.
    remove_link = re.search(
        r'class="[^"]*remove-empty-set[^"]*"\s+href="([^"]+)"', extended.text
    )
    assert remove_link and "sets=3" in remove_link.group(1)

    save_work_set(client, "left", 4, "42.5", "5")
    # The 4th row now persists without the ?sets= hint, and there is no
    # dangling "remove empty set" link for saved rows.
    base = worksets_page(client)
    assert ("left", 4) in workset_rows(base.text)
    assert "remove-empty-set" not in base.text


def test_rpe_must_be_on_the_half_point_grid_between_1_and_10(client):
    setup_tested_user(client)

    for bad_rpe in ("3.7", "0.5", "10.5"):
        response = save_work_set(client, "left", 1, "42.5", "5", rpe=bad_rpe)
        assert response.status_code in (400, 422), bad_rpe

    for good_rpe in ("1", "7.5", "10"):
        response = save_work_set(client, "left", 1, "42.5", "5", rpe=good_rpe)
        assert response.status_code == 200, good_rpe


def test_saved_sets_render_as_done_ticks(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "42.5", "5")

    page = worksets_page(client).text
    ticks = {
        (hand, int(set_number)): "checked" in attrs
        for hand, set_number, attrs in re.findall(
            r'class="set-done" data-hand="(\w+)" data-set="(\d+)"([^>]*)>', page
        )
    }

    assert ticks[("left", 1)] is True
    assert ticks[("left", 2)] is False
    assert ticks[("right", 1)] is False


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

    rows = workset_rows(worksets_page(client).text)
    # Set 3's data survives; the table shrinks back to the default rows.
    assert rows[("left", 3)] == ("42.5", "5", "")
    assert ("left", 4) not in rows


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


def test_sequential_hand_order_shows_one_hand_of_work_sets_at_a_time(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    rows = workset_rows(worksets_page(client).text)
    assert {hand for hand, n in rows} == {"left"}

    rows = workset_rows(worksets_page(client, hand="right").text)
    assert {hand for hand, n in rows} == {"right"}


def test_session_start_defaults_prefer_the_last_trained_combination(client):
    setup_tested_user(client)  # half crimp/20 tested 2026-07-01
    log_max_test(client, "left", "open hand", 10, "2026-07-02", "35")

    # Training happened on half crimp/20 after the open hand test.
    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-03")

    page = client.get("/session/new")
    grip_id = grip_type_id(client, "half crimp")
    assert f'value="{grip_id}" selected' in page.text
    assert 'name="edge_mm" value="20"' in page.text


def test_worksets_table_defaults_to_three_sets_with_protocol_reps(client):
    setup_tested_user(client)

    rows = workset_rows(worksets_page(client).text)

    assert set(rows) == {
        (hand, n) for hand in ("left", "right") for n in (1, 2, 3)
    }
    # Empty rows prefill the protocol's rep target and the hand's CurrentMax.
    assert rows[("left", 1)] == ("42.5", "5", "")
    assert rows[("right", 1)] == ("40.0", "5", "")
