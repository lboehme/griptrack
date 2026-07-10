from tests.helpers import (
    current_maxes,
    log_max_test,
    register,
    register_second_user,
)


def test_current_max_per_combination_latest_test_supersedes(client):
    register(client)

    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    assert current_maxes(client) == {("left", "half crimp", 20): 42.5}

    # A different edge on the same hand/grip is its own combination.
    log_max_test(client, "left", "half crimp", 10, "2026-07-01", "30")
    assert current_maxes(client)[("left", "half crimp", 20)] == 42.5
    assert current_maxes(client)[("left", "half crimp", 10)] == 30.0

    # A newer test supersedes even when lower (deliberate reset).
    log_max_test(client, "left", "half crimp", 20, "2026-07-02", "40")
    assert current_maxes(client)[("left", "half crimp", 20)] == 40.0


def test_max_tests_are_scoped_to_the_logged_in_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")

    register_second_user(client)

    assert current_maxes(client) == {}


def test_starter_grip_types_are_offered(client):
    register(client)

    page = client.get("/max-tests")

    assert page.status_code == 200
    for name in ("half crimp", "full crimp", "open hand", "three finger drag", "pinch"):
        assert name in page.text


def test_max_tests_page_offers_a_run_guided_test_action(client):
    register(client)

    page = client.get("/max-tests")

    assert page.status_code == 200
    assert 'action="/max-tests/guided"' in page.text


def test_max_test_date_defaults_to_today(client):
    from datetime import date

    register(client)

    page = client.get("/max-tests")

    assert f'name="date" value="{date.today().isoformat()}"' in page.text


def test_admin_can_add_a_grip_type_but_non_admin_cannot(client):
    register(client)  # founder = admin

    response = client.post(
        "/grip-types", data={"name": "mono pocket"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "mono pocket" in client.get("/max-tests").text

    register_second_user(client)  # logged in as non-admin friend now
    response = client.post(
        "/grip-types", data={"name": "sloper"}, follow_redirects=False
    )
    assert response.status_code == 403
    assert "sloper" not in client.get("/max-tests").text


def test_user_can_void_their_own_max_test(client):
    register(client)
    
    # Log a max test
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "80")
    
    assert current_maxes(client) == {("left", "half crimp", 20): 80.0}

    # Extract the test ID from the page
    page = client.get("/max-tests")
    # Using a simple substring search for the void action endpoint
    # The UI should have a form or button that posts to /max-tests/{id}/void
    import re
    match = re.search(r'action="/max-tests/(\d+)/void"', page.text)
    assert match is not None
    test_id = match.group(1)

    # Void the test
    response = client.post(f"/max-tests/{test_id}/void", follow_redirects=True)
    assert response.status_code == 200

    # The test is no longer in current_maxes (treating it as untested)
    assert current_maxes(client) == {}


def test_user_cannot_void_someone_elses_max_test(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    
    page = client.get("/max-tests")
    import re
    test_id = re.search(r'action="/max-tests/(\d+)/void"', page.text).group(1)

    register_second_user(client)
    
    response = client.post(f"/max-tests/{test_id}/void", follow_redirects=False)
    assert response.status_code == 403


def _void_actions(page_text):
    import re
    return [int(i) for i in re.findall(r'action="/max-tests/(\d+)/void"', page_text)]


def test_voiding_the_newest_test_resurfaces_the_previous_one(client):
    """The point of voided_at filtering in latest_max_test: with the newest
    (deliberate-reset) test voided, CurrentMax falls back to the older test
    — and work sets logged since *that* test's date re-enter the supersede
    rule."""
    from tests.helpers import save_work_set

    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "80")
    save_work_set(client, "left", 1, "85", "5", date="2026-07-03")
    log_max_test(client, "left", "half crimp", 20, "2026-07-05", "60")

    # Newest test supersedes everything before it, work set included.
    assert current_maxes(client)[("left", "half crimp", 20)] == 60.0

    newest_id = max(_void_actions(client.get("/max-tests").text))
    response = client.post(f"/max-tests/{newest_id}/void", follow_redirects=True)
    assert response.status_code == 200

    # Older test (2026-07-01, 80) is back, and the 85 work set logged since
    # its date supersedes it.
    assert current_maxes(client)[("left", "half crimp", 20)] == 85.0


def test_voided_test_drops_out_of_the_strength_grade_correlation(client):
    """_best_pull_at filters voided tests: with every max test voided there
    is no strength series left, so the dashboard correlation disappears."""
    from tests.test_correlation import correlation_stat, seed_progression

    seed_progression(client)
    assert correlation_stat(client) is not None

    for test_id in _void_actions(client.get("/max-tests").text):
        client.post(f"/max-tests/{test_id}/void", follow_redirects=True)

    assert correlation_stat(client) is None


def test_voided_test_no_longer_counts_as_the_last_used_combination(client):
    """last_used_combination filters voided tests: the session-start form
    default falls back to the previously used combo."""
    from tests.helpers import grip_type_id

    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "left", "open hand", 10, "2026-07-02", "35")

    page = client.get("/session/new").text
    assert f'value="{grip_type_id(client, "open hand")}" selected' in page

    newest_id = max(_void_actions(client.get("/max-tests").text))
    client.post(f"/max-tests/{newest_id}/void", follow_redirects=True)

    page = client.get("/session/new").text
    assert f'value="{grip_type_id(client, "half crimp")}" selected' in page


def test_voided_test_row_is_struck_through_and_not_voidable_again(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")

    test_id = _void_actions(client.get("/max-tests").text)[0]
    client.post(f"/max-tests/{test_id}/void", follow_redirects=True)

    page = client.get("/max-tests").text
    assert "line-through" in page
    assert ">Voided<" in page
    assert _void_actions(page) == []  # no second Void button


def test_max_test_with_invalid_hand_or_unknown_grip_is_rejected(client):
    register(client)

    bad_hand = client.post(
        "/max-tests",
        data={
            "hand": "tentacle",
            "grip_type_id": 1,
            "edge_mm": 20,
            "date": "2026-07-01",
            "weight": "40",
        },
        follow_redirects=False,
    )
    assert bad_hand.status_code == 400

    unknown_grip = client.post(
        "/max-tests",
        data={
            "hand": "left",
            "grip_type_id": 9999,
            "edge_mm": 20,
            "date": "2026-07-01",
            "weight": "40",
        },
        follow_redirects=False,
    )
    assert unknown_grip.status_code == 400


def test_adding_a_grip_type_with_an_empty_name_is_ignored(client):
    register(client)  # founder = admin
    before = client.get("/max-tests").text

    response = client.post("/grip-types", data={"name": "   "}, follow_redirects=True)
    assert response.status_code == 200
    assert client.get("/max-tests").text == before
