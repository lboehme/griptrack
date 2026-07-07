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
